source "https://rubygems.org"

# Use GitHub Pages gem (includes compatible Jekyll version)
gem "github-pages", group: :jekyll_plugins

# Plugins (most are included with github-pages gem)
group :jekyll_plugins do
  gem "jekyll-feed", "~> 0.12"
  gem "jekyll-sitemap"
  gem "jekyll-seo-tag"
end

# Windows and JRuby compatibility
platforms :mingw, :x64_mingw, :mswin, :jruby do
  gem "tzinfo", ">= 1", "< 3"
  gem "tzinfo-data"
end

# Performance booster for watching directories (disabled – wdm 0.1.1 fails to compile on Ruby 3.3+)
# gem "wdm", "~> 0.1.1", :platforms => [:mingw, :x64_mingw, :mswin]

# HTTP server for development
gem "webrick"