// charts.js — Chart.js builder helpers for NUPRC Dashboard

const FONT = "'Calibri', 'Segoe UI', sans-serif";
window.FONT = FONT;

Chart.defaults.font.family = FONT;
Chart.defaults.color = '#8A9A88';

const C = {
  crude:  '#2D6A4F',
  gas:    '#1A6B8A',
  red:    '#C0392B',
  purple: '#6B4E9E',
  gold:   '#C8920A',
  header: '#003D22',
  label:  '#8A9A88',
  value:  '#1A2820',
  border: '#E0E6DF'
};
window.C = C;

const _legend = {
  labels: {
    font:     { family: FONT, size: 11 },
    color:    '#1A2820',
    boxWidth: 12,
    padding:  12
  }
};

const _tooltip = {
  backgroundColor: '#1A2820',
  titleFont: { family: FONT, size: 11 },
  bodyFont:  { family: FONT, size: 11 },
  padding:   8,
  cornerRadius: 6
};

const _scaleBase = {
  ticks: { font: { family: FONT, size: 10 }, color: '#8A9A88', maxRotation: 45 },
  grid:  { color: 'rgba(224,230,223,0.6)' }
};

function _opts(extra) {
  return Object.assign({
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 200 },
    plugins: {
      legend:  Object.assign({ position: 'bottom' }, _legend, extra && extra.legend),
      tooltip: _tooltip
    }
  }, extra || {});
}

const ChartHelpers = {

  doughnut(ctx, labels, data, colors) {
    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data,
          backgroundColor: colors,
          borderColor: '#fff',
          borderWidth: 3,
          hoverOffset: 6
        }]
      },
      options: _opts({
        cutout: '62%',
        plugins: { legend: { position: 'bottom', labels: _legend.labels }, tooltip: _tooltip },
        scales: {}
      })
    });
  },

  bar(ctx, labels, datasets, scalesObj) {
    return new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: Object.assign(_opts(), {
        scales: scalesObj || { x: _scaleBase, y: _scaleBase }
      })
    });
  },

  line(ctx, labels, datasets, scalesObj) {
    return new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: Object.assign(_opts(), {
        scales: scalesObj || { x: _scaleBase, y: _scaleBase }
      })
    });
  },

  mixed(ctx, labels, datasets, scalesObj) {
    return new Chart(ctx, {
      type: 'bar',
      data: { labels, datasets },
      options: Object.assign(_opts(), { scales: scalesObj })
    });
  }
};

window.ChartHelpers = ChartHelpers;
