# PPTEval - Manual Local Setup Guide

## Prerequisites
- Ruby 3.1+ with DevKit
- Bundler gem

## Step-by-Step Setup

### 1. Install Ruby (Windows)
```powershell
# Download from https://rubyinstaller.org/downloads/
# Choose "Ruby+Devkit 3.1.x (x64)"
# Install with "Add to PATH" option checked
```

### 2. Restart PowerShell
Close and reopen PowerShell to refresh PATH

### 3. Verify Installation
```powershell
ruby --version        # Should show Ruby 3.1.x
gem --version         # Should show gem version
```

### 4. Install Bundler
```powershell
gem install bundler
```

### 5. Navigate to Project
```powershell
cd c:\repos\ppteval
```

### 6. Install Dependencies
```powershell
bundle install
```

### 7. Start Development Server
```powershell
bundle exec jekyll serve
```

### 8. Open in Browser
Visit: http://localhost:4000

## Development Commands

### Start with live reload
```powershell
bundle exec jekyll serve --livereload
```

### Build for production
```powershell
bundle exec jekyll build
```

### Clean build cache
```powershell
bundle exec jekyll clean
```

### Check for issues
```powershell
bundle exec jekyll doctor
```

## Troubleshooting

### Common Issues:

1. **Ruby not found after installation**
   - Restart PowerShell completely
   - Check if Ruby is in PATH: `$env:PATH -split ';' | Select-String ruby`

2. **Bundle install fails**
   - Update gem: `gem update --system`
   - Install specific version: `gem install bundler:2.4.10`

3. **Jekyll serve fails**
   - Clean and rebuild: `bundle exec jekyll clean && bundle exec jekyll build`
   - Update dependencies: `bundle update`

4. **Port already in use**
   - Use different port: `bundle exec jekyll serve --port 4001`
   - Kill existing process: `netstat -ano | findstr :4000`

### Development Tips:

- Use `--livereload` for automatic browser refresh
- Use `--drafts` to include draft posts
- Use `--incremental` for faster rebuilds
- Access site at `http://localhost:4000`

## File Watching

Jekyll automatically watches for file changes and rebuilds:
- Content files (`index.html`, `_data/*`)
- Stylesheets (`_sass/*`, `assets/css/*`)
- JavaScript (`assets/js/*`)
- Templates (`_layouts/*`, `_includes/*`)

Changes appear immediately with `--livereload` option.