/* PocketFlow – main.js */

'use strict';

// ── Delete confirmation ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.delete-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var message = form.getAttribute('data-confirm') || 'Are you sure you want to delete this expense? This cannot be undone.';
      if (!confirm(message)) {
        e.preventDefault();
      }
    });
  });
});

// ── Chart colour palette ─────────────────────────────────────────────────────
const PALETTE = [
  '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
  '#9966FF', '#FF9F40', '#6366f1', '#858796'
];

const CURRENCY_0 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0
});

const CURRENCY_2 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});

// ── Doughnut / Pie chart ─────────────────────────────────────────────────────
function initPieChart(canvasId, labels, values) {
  var ctx = document.getElementById(canvasId);
  if (!ctx || !labels || !labels.length) return;
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: PALETTE.slice(0, labels.length),
        borderWidth: 2,
        borderColor: '#fff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
              var pct   = ((ctx.raw / total) * 100).toFixed(1);
              return '  ' + CURRENCY_2.format(ctx.raw) + '  (' + pct + '%)';
            }
          }
        }
      }
    }
  });
}

// ── Column chart (category totals) ─────────────────────────────────────────
function initCategoryColumnChart(canvasId, labels, values) {
  var ctx = document.getElementById(canvasId);
  if (!ctx || !labels || !labels.length) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Category Total ($)',
        data: values,
        backgroundColor: labels.map(function (_, i) { return PALETTE[i % PALETTE.length] + 'CC'; }),
        borderColor: labels.map(function (_, i) { return PALETTE[i % PALETTE.length]; }),
        borderWidth: 1,
        borderRadius: 4,
        minBarLength: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          ticks: {
            maxRotation: 0,
            minRotation: 0
          }
        },
        y: {
          beginAtZero: true,
          ticks: { callback: function (v) { return CURRENCY_0.format(v); } }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return '  ' + CURRENCY_2.format(ctx.raw); }
          }
        }
      }
    }
  });
}

// ── Alert risk summary chart ────────────────────────────────────────────────
function initAlertSummaryChart(canvasId, riskCounts) {
  var ctx = document.getElementById(canvasId);
  if (!ctx || !riskCounts) return;

  var labels = ['Low', 'Medium', 'High'];
  var values = labels.map(function (k) { return Number(riskCounts[k] || 0); });
  var total = values.reduce(function (sum, n) { return sum + n; }, 0);
  if (total === 0) return;

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: ['#1cc88a', '#f6c23e', '#e74a3b'],
        borderColor: '#fff',
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              return '  ' + ctx.label + ': ' + ctx.raw;
            }
          }
        }
      }
    }
  });
}

// ── Bar chart (monthly trend) ────────────────────────────────────────────────
function initBarChart(canvasId, labels, values) {
  var ctx = document.getElementById(canvasId);
  if (!ctx || !labels || !labels.length) return;
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Spending ($)',
        data: values,
        backgroundColor: 'rgba(78,115,223,.75)',
        borderColor:     'rgba(78,115,223,1)',
        borderWidth: 1,
        borderRadius: 4,
        minBarLength: 3
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          ticks: { callback: function (v) { return CURRENCY_0.format(v); } }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return '  ' + CURRENCY_2.format(ctx.raw); }
          }
        }
      }
    }
  });
}
