param(
    [Parameter(Mandatory = $true)]
    [string]$DbPassword,

    [string]$Region = "us-west-1",

    [switch]$SeedAfterBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:AWS_PAGER = ""

function Invoke-TerraformApply {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModulePath,

        [switch]$NeedsDbPassword
    )

    Write-Host "`n=== Applying module: $ModulePath ===" -ForegroundColor Cyan
    Push-Location $ModulePath
    try {
        terraform init
        if ($LASTEXITCODE -ne 0) { throw "terraform init failed in $ModulePath" }

        if ($NeedsDbPassword) {
            terraform apply --auto-approve -var "db_password=$DbPassword"
        }
        else {
            terraform apply --auto-approve
        }

        if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in $ModulePath" }
    }
    finally {
        Pop-Location
    }
}

function Build-WaybackScraperZip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $zipPath = Join-Path $RepoRoot "infra/lambda/wayback_scraper.zip"
    $dockerfilePath = Join-Path $RepoRoot "infra/lambda/Dockerfile"
    $imageName = "hardware-genie-wayback-scraper-packager"
    $containerName = "hardware-genie-wayback-scraper-packager-$(New-Guid)"

    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }

    Write-Host "Building Lambda package zip with Docker..." -ForegroundColor Yellow
    docker build -f $dockerfilePath -t $imageName $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "docker build failed for Lambda package." }

    $containerId = docker create --name $containerName $imageName
    if ($LASTEXITCODE -ne 0 -or -not $containerId) { throw "docker create failed for Lambda package." }

    try {
        docker cp "${containerId}:/artifacts/wayback_scraper.zip" $zipPath
        if ($LASTEXITCODE -ne 0) { throw "docker cp failed for Lambda package." }
    }
    finally {
        docker rm $containerId | Out-Null
    }
}

function Wait-ForEcsServiceSteady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ClusterName,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    Write-Host "Waiting for ECS service to become stable..." -ForegroundColor Yellow
    aws ecs wait services-stable --cluster $ClusterName --services $ServiceName --region $Region
    if ($LASTEXITCODE -ne 0) { throw "ECS service did not become stable." }
}

function Invoke-OneTimeSeedTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ClusterName,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    Write-Host "Running one-time seed task..." -ForegroundColor Yellow

    $serviceJson = aws ecs describe-services --cluster $ClusterName --services $ServiceName --region $Region --output json | ConvertFrom-Json
    $service = $serviceJson.services[0]
    if (-not $service) { throw "Could not resolve ECS service metadata." }

    $taskDefinition = $service.taskDefinition
    $network = $service.networkConfiguration.awsvpcConfiguration
    $subnets = ($network.subnets -join ",")
    $securityGroups = ($network.securityGroups -join ",")
    $assignPublicIp = $network.assignPublicIp

    $containerName = "hardware-genie"

    $overridesPath = Join-Path $repoRoot "run_task_seed_once.json"
    @"
{
  "containerOverrides": [
    {
      "name": "$containerName",
      "environment": [
        { "name": "SEED_SQLITE_TO_RDS", "value": "true" },
        { "name": "SQLITE_SEED_PATH", "value": "/app/instance/parts.db" }
      ]
    }
  ]
}
"@ | Set-Content -Path $overridesPath -Encoding ASCII

    try {
        $networkConfig = "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$securityGroups],assignPublicIp=$assignPublicIp}"
        $taskArn = aws ecs run-task --cluster $ClusterName --task-definition $taskDefinition --launch-type FARGATE --network-configuration $networkConfig --overrides file://$overridesPath --region $Region --query "tasks[0].taskArn" --output text
        if (-not $taskArn -or $taskArn -eq "None") { throw "Seed task failed to start." }

        Write-Host "Seed task ARN: $taskArn" -ForegroundColor Yellow

        $maxWaitSeconds = 3600
        $pollInterval = 15
        $elapsed = 0
        do {
            Start-Sleep -Seconds $pollInterval
            $elapsed += $pollInterval
            $lastStatus = aws ecs describe-tasks --cluster $ClusterName --tasks $taskArn --region $Region --query "tasks[0].lastStatus" --output text
            Write-Host "[$elapsed s] Seed task status: $lastStatus" -ForegroundColor Yellow
        } while ($lastStatus -ne 'STOPPED' -and $elapsed -lt $maxWaitSeconds)

        if ($lastStatus -ne 'STOPPED') { throw "Seed task did not complete within $maxWaitSeconds seconds." }

        $taskInfo = aws ecs describe-tasks --cluster $ClusterName --tasks $taskArn --region $Region --query "tasks[0].{last:lastStatus,exit:containers[0].exitCode,stoppedReason:stoppedReason}" --output json
        Write-Host $taskInfo

        $taskId = ($taskArn -split "/")[-1]
        Write-Host "Seed task logs:" -ForegroundColor Yellow
        aws logs get-log-events --log-group-name "/ecs/hardware-genie" --log-stream-name "ecs/hardware-genie/$taskId" --region $Region --limit 5000 --query "events[*].message" --output text
    }
    finally {
        Remove-Item -Path $overridesPath -ErrorAction SilentlyContinue
    }
}

Write-Host "Starting full infrastructure build in region $Region" -ForegroundColor Yellow

Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/vpc")
Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/rds") -NeedsDbPassword
Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/docker")

Build-WaybackScraperZip -RepoRoot $repoRoot

# Deploy value analysis Lambda first so we can pass its ARN to the scraper
Push-Location (Join-Path $repoRoot "infra/value_analysis")
try {
    Write-Host "`n=== Applying module: infra/value_analysis ===" -ForegroundColor Cyan
    terraform init
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed in infra/value_analysis" }
    terraform apply --auto-approve -var "db_password=$DbPassword"
    if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in infra/value_analysis" }
    $ValueAnalysisLambdaArn  = terraform output -raw lambda_function_arn
    $ValueAnalysisLambdaName = terraform output -raw lambda_function_name
}
finally {
    Pop-Location
}

# Deploy Lambda before ECS so we can pass its ARN into the ECS module
Push-Location (Join-Path $repoRoot "infra/lambda")
try {
    Write-Host "`n=== Applying module: infra/lambda ===" -ForegroundColor Cyan
    terraform init
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed in infra/lambda" }
    terraform apply --auto-approve -var "db_password=$DbPassword" -var "value_analysis_lambda_arn=$ValueAnalysisLambdaArn" -var "value_analysis_function_name=$ValueAnalysisLambdaName"
    if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in infra/lambda" }
    $ScraperLambdaArn = terraform output -raw lambda_function_arn
    $ScraperLambdaName = terraform output -raw lambda_function_name
}
finally {
    Pop-Location
}

Push-Location (Join-Path $repoRoot "infra/ecs")
try {
    Write-Host "`n=== Applying module: infra/ecs ===" -ForegroundColor Cyan
    terraform init
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed in infra/ecs" }
    terraform apply --auto-approve -var "db_password=$DbPassword" -var "scraper_lambda_arn=$ScraperLambdaArn" -var "scraper_lambda_name=$ScraperLambdaName"
    if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in infra/ecs" }
}
finally {
    Pop-Location
}

Wait-ForEcsServiceSteady -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"

Write-Host "`nBuild complete." -ForegroundColor Green

if ($SeedAfterBuild) {
    Invoke-OneTimeSeedTask -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"
}

Write-Host "`nQuick health summary:" -ForegroundColor Green
aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region $Region --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount,taskDefinition:taskDefinition}" --output table
