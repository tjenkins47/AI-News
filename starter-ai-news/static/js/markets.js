// Markets page script — expects Chart.js UMD + date-fns adapter loaded in the HTML.

const SYMBOL = 'TSM';
const state = { range: 'ytd', interval: '1d', chart: null };

const canvas = document.getElementById('tsmChart');
const ctx = canvas.getContext('2d');

function makeGradient() {
  const h = canvas.parentElement.clientHeight || 300;
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, 'rgba(0, 123, 255, 0.35)');
  g.addColorStop(1, 'rgba(0, 123, 255, 0.00)');
  return g;
}

function pickTimeUnit(range) {
  if (range === '1d' || range === '5d') return 'hour';
  if (['1mo', '6mo', 'ytd', '1y'].includes(range)) return 'day';
  if (range === '5y') return 'month';
  return 'year';
}
function pickTooltipFormat(range) {
  if (range === '1d' || range === '5d') return "MMM d, h:mmaaa";
  if (['1mo', '6mo', 'ytd', '1y'].includes(range)) return "MMM d, yyyy";
  return "MMM yyyy";
}

async function fetchPoints() {
  const url = `/api/ohlc/${SYMBOL}?range=${state.range}&interval=${state.interval}`;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const json = await res.json();

  // Convert to {x, y} points for Chart.js time scale
  const pts = (json.points || [])
    .filter(p => Number.isFinite(p.t) && Number.isFinite(p.c))
    .map(p => ({ x: +p.t, y: +p.c }));

  console.log(`Fetched ${pts.length} points for ${SYMBOL} (${state.range}/${state.interval})`);
  return pts;
}

function buildChart(pts) {
  if (state.chart) state.chart.destroy();

  state.chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: `${SYMBOL} price`,
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
        tooltip: { callbacks: { label: c => ` $${c.parsed.y?.toFixed(2)}` } }
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

// Initial draw when the DOM is ready
document.addEventListener('DOMContentLoaded', refresh);
