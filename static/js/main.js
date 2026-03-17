/* PocketFlow – main.js */

'use strict';

// ── Delete confirmation ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.delete-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      if (!confirm('Are you sure you want to delete this expense? This cannot be undone.')) {
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
              return '  $' + ctx.raw.toFixed(2) + '  (' + pct + '%)';
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
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          beginAtZero: true,
          ticks: { callback: function (v) { return '$' + v.toFixed(0); } }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return '  $' + ctx.raw.toFixed(2); }
          }
        }
      }
    }
  });
}
