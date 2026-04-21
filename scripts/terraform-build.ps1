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
        aws ecs wait tasks-stopped --cluster $ClusterName --tasks $taskArn --region $Region

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
Invoke-TerraformApply -ModulePath (Join-Path $repoRoot "infra/ecs") -NeedsDbPassword

Wait-ForEcsServiceSteady -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"

Write-Host "`nBuild complete." -ForegroundColor Green

if ($SeedAfterBuild) {
    Invoke-OneTimeSeedTask -ClusterName "hardware-genie-cluster" -ServiceName "hardware-genie-service"
}

Write-Host "`nQuick health summary:" -ForegroundColor Green
aws ecs describe-services --cluster hardware-genie-cluster --services hardware-genie-service --region $Region --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount,taskDefinition:taskDefinition}" --output table
