param(
    [Parameter(Mandatory = $true)]
    [string]$DbPassword,

    [string]$Region = "us-west-1",

    [string]$AllowedSshCidr = "",

    [switch]$SeedAfterBuild,

    [switch]$SeedOnly
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

function Remove-OrphanedLambdaResources {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FunctionName,

        [switch]$HasEventBridgeRule
    )

    $roleName = "$FunctionName-role"
    $sgName = "$FunctionName-sg"
    $logGroupName = "/aws/lambda/$FunctionName"
    $scheduleName = "$FunctionName-schedule"

    Write-Host "Checking for orphaned resources for $FunctionName ..." -ForegroundColor Yellow

    $oldErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # Delete function if it exists (non-fatal if it doesn't)
        aws lambda get-function --function-name $FunctionName --region $Region 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            aws lambda delete-function --function-name $FunctionName --region $Region 1>$null 2>$null
            Write-Host "Deleted existing Lambda function $FunctionName" -ForegroundColor Yellow
        }

        if ($HasEventBridgeRule) {
            aws events describe-rule --name $scheduleName --region $Region 1>$null 2>$null
            if ($LASTEXITCODE -eq 0) {
                aws events remove-targets --rule $scheduleName --ids "wayback-scraper" --region $Region 1>$null 2>$null
                aws events delete-rule --name $scheduleName --region $Region 1>$null 2>$null
                Write-Host "Removed EventBridge rule $scheduleName" -ForegroundColor Yellow
            }
        }

        $rdsSgId = aws ec2 describe-security-groups --filters "Name=group-name,Values=hardware-genie-postgres-sg" --region $Region --query "SecurityGroups[0].GroupId" --output text 2>$null
        if ($rdsSgId -eq 'None') { $rdsSgId = $null }

        $lambdaSgId = aws ec2 describe-security-groups --filters "Name=group-name,Values=$sgName" --region $Region --query "SecurityGroups[0].GroupId" --output text 2>$null
        if ($lambdaSgId -and $lambdaSgId -ne 'None') {
            if ($rdsSgId) {
                aws ec2 revoke-security-group-ingress --group-id $rdsSgId --protocol tcp --port 5432 --source-group $lambdaSgId --region $Region 1>$null 2>$null
                Write-Host "Revoked postgres ingress from $lambdaSgId" -ForegroundColor Yellow
            }

            $deleted = $false
            for ($attempt = 1; $attempt -le 5; $attempt++) {
                aws ec2 delete-security-group --group-id $lambdaSgId --region $Region 1>$null 2>$null
                if ($LASTEXITCODE -eq 0) { $deleted = $true; break }

                Write-Host "Waiting for Lambda ENI cleanup before deleting $sgName (attempt $attempt/5) ..." -ForegroundColor Yellow
                Start-Sleep -Seconds 10
            }

            if (-not $deleted) {
                Write-Warning "Could not delete orphaned security group $sgName. Terraform will handle it on apply."
            }
            else {
                Write-Host "Deleted security group $sgName" -ForegroundColor Yellow
            }
        }

        aws logs describe-log-groups --log-group-name-prefix $logGroupName --region $Region --query "logGroups[0].logGroupName" --output text 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            aws logs delete-log-group --log-group-name $logGroupName --region $Region 1>$null 2>$null
            Write-Host "Deleted log group $logGroupName" -ForegroundColor Yellow
        }

        $managedPolicies = aws iam list-attached-role-policies --role-name $roleName --query "AttachedPolicies[].PolicyArn" --output text 2>$null
        if ($managedPolicies) {
            foreach ($policyArn in ($managedPolicies -split "`t|\s+" | Where-Object { $_ })) {
                aws iam detach-role-policy --role-name $roleName --policy-arn $policyArn 1>$null 2>$null
            }
        }

        $inlinePolicies = aws iam list-role-policies --role-name $roleName --query "PolicyNames[]" --output text 2>$null
        if ($inlinePolicies) {
            foreach ($policyName in ($inlinePolicies -split "`t|\s+" | Where-Object { $_ })) {
                aws iam delete-role-policy --role-name $roleName --policy-name $policyName 1>$null 2>$null
            }
        }

        aws iam get-role --role-name $roleName 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            aws iam delete-role --role-name $roleName 1>$null 2>$null
            Write-Host "Deleted IAM role $roleName" -ForegroundColor Yellow
        }
    }
    finally {
        $ErrorActionPreference = $oldErrorAction
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

if ($SeedOnly) {
    Wait-ForEcsServiceSteady -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"
    Invoke-OneTimeSeedTask -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"
    exit 0
}

Write-Host "Starting full infrastructure build in region $Region" -ForegroundColor Yellow

Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/vpc")
# Apply RDS module. If AllowedSshCidr was provided, pass it to terraform to avoid interactive input.
$rdsModulePath = (Join-Path $repoRoot "infra/rds")
Push-Location $rdsModulePath
try {
    Write-Host "`n=== Applying module: infra/rds ===" -ForegroundColor Cyan
    terraform init
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed in infra/rds" }

    if ([string]::IsNullOrEmpty($AllowedSshCidr)) {
        terraform apply --auto-approve -var "db_password=$DbPassword"
    }
    else {
        terraform apply --auto-approve -var "db_password=$DbPassword" -var "allowed_ssh_cidr=$AllowedSshCidr"
    }

    if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in infra/rds" }
}
finally {
    Pop-Location
}
Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/docker")

Build-WaybackScraperZip -RepoRoot $repoRoot

Remove-OrphanedLambdaResources -FunctionName "hardware-genie-value-analysis"

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

Remove-OrphanedLambdaResources -FunctionName "hardware-genie-wayback-scraper" -HasEventBridgeRule

# If the SG still exists after cleanup (e.g. ENIs not yet detached), import it into
# Terraform state so apply updates it in-place instead of failing with Duplicate.
$lambdaModulePath = Join-Path $repoRoot "infra/lambda"
$existingSgId = aws ec2 describe-security-groups --filters "Name=group-name,Values=hardware-genie-wayback-scraper-sg" --region $Region --query "SecurityGroups[0].GroupId" --output text 2>$null
if ($existingSgId -and $existingSgId -ne 'None') {
    Write-Host "SG hardware-genie-wayback-scraper-sg ($existingSgId) still exists - importing into Terraform state..." -ForegroundColor Yellow
    Push-Location $lambdaModulePath
    try {
        terraform init -input=false | Out-Null
        terraform import -var "db_password=$DbPassword" -var "value_analysis_lambda_arn=$ValueAnalysisLambdaArn" -var "value_analysis_function_name=$ValueAnalysisLambdaName" aws_security_group.lambda $existingSgId
    } finally {
        Pop-Location
    }
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
