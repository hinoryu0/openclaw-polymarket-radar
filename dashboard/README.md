# Kyiv Strike Markets Dashboard

A beautiful, responsive visual dashboard for monitoring Kyiv strike prediction markets on Polymarket.

## Features

- **Real-time Market Data**: Displays strike probability markets for upcoming dates
- **Key Metrics**: Probability, spread, volume, 1h/24h price changes
- **Visual Indicators**: Color-coded arrows showing price movements
- **Interactive Charts**: Probability trends and volume distribution using Chart.js
- **Anomaly Detection**: Automatically identifies mispriced markets and unusual patterns
- **Auto-refresh**: Updates every 60 seconds automatically
- **Dark Theme**: Modern dark UI with excellent contrast

## Quick Start

Simply open `index.html` in your web browser:

```bash
# From this directory
open index.html        # macOS
xdg-open index.html    # Linux
start index.html       # Windows
```

Or serve via a local server for better compatibility:

```bash
# Python 3
python -m http.server 8080

# Node.js
npx serve .

# Then open http://localhost:8080
```

## Data Sources

The dashboard attempts to fetch data from Polymarket's Gamma API:
- Primary: `https://gamma-api.polymarket.com/events`
- Markets are filtered for Kyiv-related strike events

**Note**: Due to browser CORS restrictions, direct API calls may fail. The dashboard includes realistic mock data as a fallback for demonstration purposes.

### For Live Data

To use real market data, serve this dashboard through a CORS-enabled proxy or use a browser extension that disables CORS for local development.

## Market Indicators

| Indicator | Description |
|-----------|-------------|
| **Probability** | Chance of strike occurring (based on market price) |
| **Spread** | Bid-ask spread as percentage (lower = better liquidity) |
| **Volume** | 24-hour trading volume in USD |
| **1h Change** | Price change over last hour |
| **24h Change** | Price change over last 24 hours |

## Anomaly Types

- **Price Inversion**: Later date has lower probability than earlier date
- **Price Spike**: Unusual jump in probability
- **Low Liquidity**: Wide bid-ask spread
- **Volume Anomaly**: High volume on low-probability event
- **Rapid Movement**: Significant price change in 1 hour

## Keyboard Shortcuts

- **R** - Manual refresh
- **F** - Filter markets
- **S** - Sort by column

## Customization

Edit the `CONFIG` object in `index.html`:

```javascript
const CONFIG = {
    refreshInterval: 60000,  // Auto-refresh interval in ms
    apiBaseUrl: 'https://gamma-api.polymarket.com',
    kyivKeywords: ['kyiv', 'kiev', 'strike', 'ukraine capital']
};
```

## Browser Compatibility

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Android)

## Dependencies

All loaded via CDN:
- Chart.js 4.4.1 - Charts and visualizations
- Font Awesome 6.5.1 - Icons

No build step required - pure HTML/CSS/JS.

## File Structure

```
dashboard/
├── index.html      # Main dashboard (self-contained)
└── README.md       # This file
```

## License

MIT - Free for personal and commercial use.

## Notes

- Data is for informational purposes only
- Not financial advice
- Market data may have delays
