# PPTArena - Jekyll Setup Instructions

## Local Development Setup

### Prerequisites
- Ruby 2.7+ (recommended 3.1+)
- Bundler gem
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/microsoft/PPTArena.git
   cd PPTArena
   ```

2. **Install dependencies:**
   ```bash
   # If you get dependency conflicts, try:
   bundle update
   # Then:
   bundle install
   ```

3. **Build and serve locally:**
   ```bash
   bundle exec jekyll serve
   ```

4. **Open in browser:**
   Visit `http://localhost:4000`

### Development Workflow

- **Content Updates**: Edit `index.html` and data files in `_data/`
- **Styling Changes**: Modify SCSS files in `_sass/`
- **Layout Updates**: Edit templates in `_layouts/` and `_includes/`
- **JavaScript**: Update `assets/js/main.js`

### Adding Content

#### Updating Authors
Edit `_data/authors.yml`:
```yaml
- name: "Your Name"
  affiliation: "1"
  url: "https://yourwebsite.com"
```

#### Adding Benchmark Results
Edit `_data/benchmark.yml`:
```yaml
results:
  - model: "Your Model"
    type: "General|Specialized|Agentic"
    success_rate: 25.5
    max_steps: 20
    category: "Foundation|Specialized|Agentic"
```

#### Updating Navigation
Edit `_data/navigation.yml` to add/modify navigation items.

### Deployment

The site automatically deploys to GitHub Pages when you push to the main branch using GitHub Actions.

### Customization

1. **Site Settings**: Update `_config.yml`
2. **Colors/Fonts**: Modify CSS variables in `_sass/_base.scss`
3. **Layout**: Edit templates in `_layouts/`
4. **Components**: Modify files in `_includes/`

### Troubleshooting

#### Common Issues:
- **Build Errors**: Check Ruby/Jekyll versions
- **Style Issues**: Verify SCSS syntax
- **Data Problems**: Validate YAML formatting

#### Useful Commands:
```bash
# Clean build cache
bundle exec jekyll clean

# Build for production
JEKYLL_ENV=production bundle exec jekyll build

# Check for issues
bundle exec jekyll doctor
```

## GitHub Pages Configuration

The site is configured to deploy automatically via GitHub Actions. To enable:

1. Go to repository Settings → Pages
2. Set Source to "GitHub Actions"
3. Push changes to trigger deployment

## Performance Optimization

- Images are optimized for web
- CSS/JS is minified in production
- Lazy loading implemented for better performance
- SEO optimized with proper meta tags

## Browser Support

- Modern browsers (Chrome, Firefox, Safari, Edge)
- Responsive design for mobile devices
- Progressive enhancement for older browsers