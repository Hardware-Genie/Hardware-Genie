param(
    [Parameter(Mandatory = $true)]
    [string]$DbPassword,

    [string]$Region = "us-west-1",

    [string]$EcrRepository = "hardware-genie",

    [switch]$SkipEcsScaleDown
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:AWS_PAGER = ""

function Invoke-TerraformDestroy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModulePath,

        [switch]$NeedsDbPassword
    )

    Write-Host "`n=== Destroying module: $ModulePath ===" -ForegroundColor Cyan
    Push-Location $ModulePath
    try {
        terraform init
        if ($LASTEXITCODE -ne 0) { throw "terraform init failed in $ModulePath" }

        if ($NeedsDbPassword) {
            terraform destroy --auto-approve -var "db_password=$DbPassword"
        }
        else {
            terraform destroy --auto-approve
        }

        if ($LASTEXITCODE -ne 0) { throw "terraform destroy failed in $ModulePath" }
    }
    finally {
        Pop-Location
    }
}

function Clear-EcrRepositoryImages {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepositoryName
    )

    Write-Host "`n=== Clearing ECR repository images: $RepositoryName ===" -ForegroundColor Cyan

    while ($true) {
        $raw = aws ecr list-images --repository-name $RepositoryName --region $Region --max-items 100 --output json 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $raw) {
            Write-Warning "Unable to list ECR images for $RepositoryName (repo may not exist yet)."
            break
        }

        $payload = $raw | ConvertFrom-Json
        if (-not $payload.imageIds -or $payload.imageIds.Count -eq 0) {
            Write-Host "ECR repository is already empty." -ForegroundColor Yellow
            break
        }

        $imageIdsFile = Join-Path $env:TEMP ("ecr-image-ids-" + [System.Guid]::NewGuid().ToString() + ".json")
        try {
            ($payload.imageIds | ConvertTo-Json -Compress) | Set-Content -Path $imageIdsFile -Encoding ASCII
            aws ecr batch-delete-image --repository-name $RepositoryName --region $Region --image-ids ("file://" + $imageIdsFile) | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Failed deleting ECR images from $RepositoryName"
            }
        }
        finally {
            Remove-Item -Path $imageIdsFile -ErrorAction SilentlyContinue
        }

        Write-Host "Deleted $($payload.imageIds.Count) image references from $RepositoryName." -ForegroundColor Yellow
    }
}

Write-Host "Starting full infrastructure destroy in region $Region" -ForegroundColor Yellow

if (-not $SkipEcsScaleDown) {
    Write-Host "Attempting ECS service scale-down to speed cleanup..." -ForegroundColor Yellow
    try {
        aws ecs update-service --cluster hardware-genie-cluster --service hardware-genie-service --desired-count 0 --region $Region | Out-Null
    }
    catch {
        Write-Warning "ECS scale-down skipped: $($_.Exception.Message)"
    }
}

Invoke-TerraformDestroy -ModulePath (Join-Path $repoRoot "infra/ecs") -NeedsDbPassword
Invoke-TerraformDestroy -ModulePath (Join-Path $repoRoot "infra/lambda") -NeedsDbPassword
Clear-EcrRepositoryImages -RepositoryName $EcrRepository
Invoke-TerraformDestroy -ModulePath (Join-Path $repoRoot "infra/docker")
Invoke-TerraformDestroy -ModulePath (Join-Path $repoRoot "infra/rds") -NeedsDbPassword
Invoke-TerraformDestroy -ModulePath (Join-Path $repoRoot "infra/vpc")

Write-Host "`nDestroy complete." -ForegroundColor Green
