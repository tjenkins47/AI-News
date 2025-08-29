// markets.js — minimal Yahoo proxy + Chart.js line chart

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const titleEl = $("#symbolTitle");
  const canvas = $("#tsmChart");
  const ctx = canvas.getContext("2d");

  const state = {
    symbol: (titleEl?.textContent || "TSM").trim().toUpperCase(),
    range: ($(".range-btn.active")?.dataset.range || "ytd"),
    interval: ($(".range-btn.active")?.dataset.interval || "1d"),
  };

  let chart;

  async function fetchSeries() {
    const url = `/api/price_history?symbol=${encodeURIComponent(state.symbol)}&range=${encodeURIComponent(state.range)}&interval=${encodeURIComponent(state.interval)}`;
    const r = await fetch(url);
    const j = await r.json();
    const pts = (j.candles || [])
      .filter(p => p && typeof p.c === "number" && typeof p.t === "number")
      .map(p => ({ x: p.t, y: p.c }));
    return pts;
  }

  function render(points) {
    if (chart) {
      chart.data.datasets[0].label = state.symbol;
      chart.data.datasets[0].data = points;
      chart.update();
      return;
    }
    chart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [{
          label: state.symbol,
          data: points,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.15,
          borderColor: "#9fd1ff",
        }]
      },
      options: {
        parsing: false,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: true }
        },
        scales: {
          x: {
            type: "time",
            time: { tooltipFormat: "PPp" },
            grid: { color: "rgba(255,255,255,0.08)" },
            ticks: { color: "#cfe6ff", maxRotation: 0 }
          },
          y: {
            grid: { color: "rgba(255,255,255,0.08)" },
            ticks: { color: "#cfe6ff" }
          }
        }
      }
    });
  }

  async function loadAndDraw() {
    titleEl.textContent = state.symbol;
    const points = await fetchSeries();
    render(points);
  }

  // symbol pills
  $$(".symbol-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".symbol-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.symbol = btn.dataset.symbol.toUpperCase();
      loadAndDraw();
    });
  });

  // range buttons
  $$(".range-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      $$(".range-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.range = btn.dataset.range;
      state.interval = btn.dataset.interval;
      loadAndDraw();
    });
  });

  // initial render
  loadAndDraw();
})();
