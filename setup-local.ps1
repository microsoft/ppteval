#!/usr/bin/env powershell

# PPTEval Local Development Setup Script
Write-Host "Setting up PPTEval local development environment..." -ForegroundColor Green

# Check if Ruby is installed
try {
    $rubyVersion = ruby --version 2>$null
    Write-Host "Ruby is already installed: $rubyVersion" -ForegroundColor Green
} catch {
    Write-Host "Ruby not found. Please install Ruby first:" -ForegroundColor Yellow
    Write-Host "1. Visit https://rubyinstaller.org/downloads/" -ForegroundColor Yellow
    Write-Host "2. Download Ruby+Devkit 3.1.x (x64)" -ForegroundColor Yellow
    Write-Host "3. Run installer and add to PATH" -ForegroundColor Yellow
    Write-Host "4. Restart PowerShell and run this script again" -ForegroundColor Yellow
    exit 1
}

# Check if Bundler is installed
try {
    bundler --version 2>$null
    Write-Host "Bundler is already installed" -ForegroundColor Green
} catch {
    Write-Host "Installing Bundler..." -ForegroundColor Yellow
    gem install bundler
}

# Install dependencies
Write-Host "Installing Jekyll and dependencies..." -ForegroundColor Yellow
bundle install

# Build and serve the site
Write-Host "Starting Jekyll development server..." -ForegroundColor Green
Write-Host "Site will be available at: http://localhost:4000" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow

bundle exec jekyll serve --livereload