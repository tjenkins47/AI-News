// static/js/main.js

(function () {
  const PREVIEW_LIMIT = 380;

  // Robust preview: strip HTML, collapse whitespace, word-safe ellipsis
  function textPreview(text, limit = PREVIEW_LIMIT) {
    if (!text) return "";
    const s = String(text);
    const temp = document.createElement("div");
    temp.innerHTML = s; // strip tags safely
    const stripped = (temp.textContent || temp.innerText || "").replace(/\s+/g, " ").trim();
    if (stripped.length <= limit) return stripped;
    const cut = stripped.slice(0, limit);
    const lastSpace = cut.lastIndexOf(" ");
    return (lastSpace > 40 ? cut.slice(0, lastSpace) : cut) + "…";
  }

  // Build a story card (used only if we *client*-render)
  function makeCard(item, lang = "EN") {
    const title = (item.title && (item.title[lang.toLowerCase()] || item.title.en)) || "";
    const summaryRaw = (item.summary && (item.summary[lang.toLowerCase()] || item.summary.en)) || "";
    const url = item.url || "#";
    const categories = item.categories || [];
    const tags = item.tags || [];

    const card = document.createElement("div");
    card.className = "col-md-6 story";
    card.innerHTML = `
      <div class="card h-100">
        <div class="card-body">
          <h5 class="card-title">${title}</h5>
          <p class="card-text summary">${textPreview(summaryRaw)}</p>
          <a class="btn btn-primary mt-1" target="_blank" rel="noopener">Read more</a>
          <div class="mt-2"></div>
        </div>
      </div>
    `;
    card.querySelector("a").href = url;

    // Badges
    const badges = card.querySelector(".mt-2");
    const hasFinance = tags.includes("finance") || categories.map(c => String(c).toLowerCase()).includes("finance");
    if (hasFinance) {
      const b = document.createElement("span");
      b.className = "badge bg-secondary me-1";
      b.textContent = "Finance";
      badges.appendChild(b);
    }
    for (const c of categories) {
      if (hasFinance && String(c).toLowerCase() === "finance") continue;
      const b = document.createElement("span");
      b.className = "badge bg-secondary me-1";
      b.textContent = c;
      badges.appendChild(b);
    }
    return card;
  }

  async function hydrateIfNeeded() {
    const container = document.getElementById("news-container");
    if (!container) return;

    // If server already rendered cards, enforce clamp on them and exit.
    const preRendered = container.querySelector(".card");
    if (preRendered) {
      container.querySelectorAll(".card .card-text").forEach(p => {
        // Only touch if it's not already clamped or is suspiciously long
        if (!p.classList.contains("summary") || (p.textContent && p.textContent.length > PREVIEW_LIMIT + 40)) {
          p.textContent = textPreview(p.textContent);
          p.classList.add("summary");
        }
      });
      return;
    }

    // Otherwise, client-render from /api/news (shape: either {items:[...]} or [...] )
    try {
      const res = await fetch("/api/news", { cache: "no-store" });
      const data = await res.json();
      const items = Array.isArray(data) ? data : (data.items || []);
      const lang = (localStorage.getItem("lang") || "EN").toUpperCase();

      const frag = document.createDocumentFragment();
      for (const item of items) frag.appendChild(makeCard(item, lang));
      container.appendChild(frag);
    } catch (e) {
      console.warn("Failed to hydrate news:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", hydrateIfNeeded);
})();
