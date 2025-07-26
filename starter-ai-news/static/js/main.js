document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("news-container");

  // Only allow EN or FR
  let storedLang = localStorage.getItem("lang");
  const allowedLangs = ["EN", "FR"];
  if (!storedLang || !allowedLangs.includes(storedLang.toUpperCase())) {
    storedLang = "EN";
    localStorage.setItem("lang", storedLang);
  } else {
    storedLang = storedLang.toUpperCase();
  }

  //console.log("🗣 Using language:", storedLang);
  setSelectedLangLabel(storedLang);
  loadNews(storedLang);

  // Add event listeners to language menu
  document.querySelectorAll(".lang-select").forEach(el => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const raw = e.target.getAttribute("data-lang");
      if (!raw) {
        console.warn("Missing data-lang attribute on clicked item:", e.target);
        return;
      }

      const selectedLang = raw.toUpperCase();
      if (!allowedLangs.includes(selectedLang)) {
        console.warn("Invalid language selected:", selectedLang);
        return;
      }

      localStorage.setItem("lang", selectedLang);
      setSelectedLangLabel(selectedLang);
      loadNews(selectedLang);
    });
  });

  function setSelectedLangLabel(lang) {
    const label = document.getElementById("selected-lang");
    if (label) {
      label.textContent = lang;
    }
  }

  function loadNews(lang) {
    fetch("/api/news")
      .then(res => res.json())
      .then(data => {
        container.innerHTML = "";

        data.forEach(story => {
          const card = document.createElement("div");
          card.className = "col-md-6 mb-4";

          const title =
            story.title?.[lang] ||
            story.title?.[lang.toLowerCase()] ||
            story.title?.EN ||
            story.title?.en ||
            story.title?.FR ||
            story.title?.fr ||
            "Untitled";

          const summary =
            story.summary?.[lang] ||
            story.summary?.[lang.toLowerCase()] ||
            story.summary?.EN ||
            story.summary?.en ||
            story.summary?.FR ||
            story.summary?.fr ||
            "No summary available.";

          card.innerHTML = `
            <div class="card h-100">
              <div class="card-body">
                <div class="mb-2">
                  ${(story.categories || []).map(cat => `
                    <span class="badge bg-${getBadgeColor(cat)} me-1">${cat}</span>
                  `).join('')}
                </div>
                <h5 class="card-title">${title}</h5>
                <p class="card-text">${summary}</p>
                <a href="${story.url}" class="btn btn-primary" target="_blank">Read more</a>
              </div>
            </div>`;
          container.appendChild(card);
        });
      });
  }

  function getBadgeColor(category) {
    switch (category) {
      case "Model": return "info";
      case "Company": return "success";
      case "Agent AI": return "warning";
      default: return "secondary";
    }
  }
});
