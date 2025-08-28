// Markets page script — Chart.js UMD + date-fns adapter must be loaded by markets.html

const state = {
  symbol: 'TSM',
  range: 'ytd',
  interval: '1d',
  chart: null
};

const titleEl = document.getElementById('symbolTitle');
const canvas = document.getElementById('tsmChart');
const ctx = canvas.getContext('2d');

function makeGradient() {
  const h = canvas.parentElement.clientHeight || 300;
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, 'rgba(0, 123, 255, 0.35)');
  g.addColorStop(1, 'rgba(0, 123, 255, 0.00)');
  return g;
}
const pickTimeUnit = (r) =>
  (r === '1d' || r === '5d') ? 'hour' :
  (['1mo','6mo','ytd','1y'].includes(r) ? 'day' :
   (r === '5y' ? 'month' : 'year'));
const pickTooltipFormat = (r) =>
  (r === '1d' || r === '5d') ? "MMM d, h:mmaaa" :
  (['1mo','6mo','ytd','1y'].includes(r) ? "MMM d, yyyy" : "MMM yyyy");

async function fetchPoints() {
  const url = `/api/ohlc/${state.symbol}?range=${state.range}&interval=${state.interval}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();
  const pts = (json.points || [])
    .filter(p => Number.isFinite(p.t) && Number.isFinite(p.c))
    .map(p => ({ x: +p.t, y: +p.c }));
  console.log(`Fetched ${pts.length} points for ${state.symbol} (${state.range}/${state.interval})`);
  return pts;
}

function buildChart(pts) {
  if (state.chart) state.chart.destroy();
  state.chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: `${state.symbol} price`,
        data: pts,
        borderWidth: 2,
        borderColor: 'rgba(0, 123, 255, 1)',
        backgroundColor: makeGradient(),
        fill: true,
        pointRadius: 0,
        tension: 0.25
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => ` $${c.parsed.y?.toFixed(2)}` } }
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: pickTimeUnit(state.range), tooltipFormat: pickTooltipFormat(state.range) },
          ticks: { maxRotation: 0, autoSkip: true }
        },
        y: {
          beginAtZero: false,
          ticks: { callback: v => `$${Number(v).toFixed(2)}` },
          grid: { drawBorder: false }
        }
      }
    }
  });
}

let inFlight = false;
async function refresh() {
  if (inFlight) return;
  inFlight = true;
  canvas.style.opacity = 0.6;
  try {
    const pts = await fetchPoints();
    buildChart(pts);
  } catch (e) {
    console.error('Failed to draw chart:', e);
  } finally {
    canvas.style.opacity = 1;
    inFlight = false;
  }
}

// Range buttons
document.querySelectorAll('.range-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.range = btn.dataset.range;
    state.interval = btn.dataset.interval;
    await refresh();
  });
});

// Symbol pills
document.querySelectorAll('.symbol-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    document.querySelectorAll('.symbol-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.symbol = btn.dataset.symbol;
    titleEl.textContent = state.symbol;
    await refresh();
  });
});

// Initial draw
document.addEventListener('DOMContentLoaded', refresh);
