document.addEventListener("DOMContentLoaded", () => {
  const lang = (localStorage.getItem("lang") || "en").toLowerCase();
  setLangLabel(lang);
  fetch("/api/news")
    .then(res => res.json())
    .then(data => {
      const container = document.getElementById("news-container");
      container.innerHTML = "";
      data.forEach(story => {
        const title = story.title[lang] || story.title["en"];
        const summary = story.summary[lang] || story.summary["en"];
        const card = document.createElement("div");
        card.className = "col-md-6 mb-4";
        card.innerHTML = `
          <div class="card h-100">
            <div class="card-body">
              <h5 class="card-title">${title}</h5>
              <p class="card-text">${summary}</p>
              <a href="${story.url}" class="btn btn-primary" target="_blank">Read more</a>
            </div>
          </div>`;
        container.appendChild(card);
      });
    });

  document.querySelectorAll(".lang-select").forEach(el => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const selected = e.target.getAttribute("data-lang").toLowerCase();
      localStorage.setItem("lang", selected);
      location.reload();
    });
  });
});

function setLangLabel(lang) {
  const label = document.getElementById("selected-lang");
  if (label) label.textContent = lang.toUpperCase();
}
