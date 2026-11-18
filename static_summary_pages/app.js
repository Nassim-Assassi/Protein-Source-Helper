const $ = (selector) => document.querySelector(selector);

let dashboardData = null;
let activeRanking = "value_focused_overall";

const formatCurrency = (value) => value == null
  ? "—"
  : new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 2 }).format(value);

const formatNumber = (value, digits = 2) => value == null
  ? "—"
  : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);

const formatTimestamp = (value) => value
  ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "Not available";

function createElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}

function safeSourceUrl(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value, window.location.href);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch (_) {
    return null;
  }
}

async function loadData() {
  try {
    const response = await fetch("data/dashboard-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Data export returned ${response.status}`);
    dashboardData = await response.json();
    renderDashboard();
  } catch (error) {
    $("#loading-state").hidden = true;
    $("#error-state").hidden = false;
    $("#error-state").textContent = `Unable to load dashboard data: ${error.message}`;
  }
}

function renderDashboard() {
  $("#loading-state").hidden = true;
  $("#dashboard").hidden = false;
  $("#latest-scrape").textContent = formatTimestamp(dashboardData.latest_scrape_finished_at);
  renderKpis();
  renderInsights();
  renderRetailerChart();
  renderCoverage();
  renderTable();
}

function renderKpis() {
  const kpis = dashboardData.kpis;
  const cards = [
    ["In-stock product count", kpis.individual_listings?.toLocaleString("en-GB")],
    ["Retailers", kpis.retailers?.toLocaleString("en-GB")],
    ["Brands", kpis.brands?.toLocaleString("en-GB")],
    ["Average cost / 100 kcal", formatCurrency(kpis.average_cost_per_100_kcal)],
    ["Average protein / 100 kcal", `${formatNumber(kpis.average_protein_per_100_kcal)} g`],
    ["Average cost / 100 g protein", formatCurrency(kpis.average_cost_per_100g_protein)],
  ];
  const grid = $("#kpi-grid");
  grid.replaceChildren(...cards.map(([label, value]) => {
    const card = createElement("article", "kpi-card");
    card.append(createElement("span", "", label));
    card.append(createElement("strong", "", value ?? "—"));
    return card;
  }));
}

function productLabel(product) {
  return product.name || product.canonical_product_name || "Unnamed listing";
}

function renderInsights() {
  const bestOverall = dashboardData.rankings.balanced_overall[0];
  const cheapest = dashboardData.rankings.cost_per_100_kcal[0];
  $("#best-overall").textContent = bestOverall ? productLabel(bestOverall) : "—";
  $("#best-overall-detail").textContent = bestOverall
    ? bestOverall.retailer_name
    : "No valid scores in this export";
  $("#lowest-cost").textContent = cheapest ? formatCurrency(cheapest.cost_per_100_kcal) : "—";
  $("#lowest-cost-detail").textContent = cheapest
    ? `${productLabel(cheapest)} · ${cheapest.retailer_name}`
    : "No valid metric in this export";
  $("#eligible-count").textContent = dashboardData.coverage.eligible_in_stock_listings?.toLocaleString("en-GB") ?? "—";
}

function renderRetailerChart() {
  const measure = $("#value-measure").value;
  let rows = [...dashboardData.retailers];
  const isCount = measure === "listing_count";
  rows.sort((a, b) => (b[measure] || 0) - (a[measure] || 0));
  const max = Math.max(...rows.map(row => row[measure] || 0), 1);
  const chart = $("#retailer-chart");
  if (!rows.length) {
    chart.replaceChildren(createElement("p", "chart-note", "No retailer averages are available."));
    return;
  }

  chart.replaceChildren(...rows.map(row => {
    const value = row[measure];
    const display = isCount ? value?.toLocaleString("en-GB") : formatNumber(value);
    const width = value == null ? 0 : Math.max(2, ((value / max) * 100));
    const item = createElement("div", "bar-row");
    const name = createElement("span", "bar-name", row.retailer_name ?? "—");
    name.title = row.retailer_name ?? "";

    const track = createElement("div", "bar-track");
    const fill = createElement("div", "bar-fill");
    fill.style.width = `${width}%`;
    track.append(fill);

    item.append(name, track, createElement("span", "bar-value", display ?? "—"));
    return item;
  }));
}

function renderCoverage() {
  const coverage = dashboardData.coverage;
  const kpis = dashboardData.kpis;
  const items = [
    ["Active listings", coverage.active_listings],
    ["Eligible in stock", coverage.eligible_in_stock_listings],
    ["Retailers", kpis.retailers],
    ["Brands", kpis.brands],
    ["Barcode coverage", `${coverage.listings_with_barcode?.toLocaleString("en-GB") ?? 0} / ${coverage.total_listings?.toLocaleString("en-GB") ?? 0}`],
    ["Image coverage", `${coverage.listings_with_image?.toLocaleString("en-GB") ?? 0} / ${coverage.total_listings?.toLocaleString("en-GB") ?? 0}`],
    ["Source coverage", `${coverage.listings_with_source?.toLocaleString("en-GB") ?? 0} / ${coverage.total_listings?.toLocaleString("en-GB") ?? 0}`],
    ["Data updated", formatTimestamp(dashboardData.latest_scrape_finished_at)],
  ];
  $("#coverage-grid").replaceChildren(...items.map(([label, value]) => {
    const item = createElement("article", "coverage-item");
    item.append(createElement("span", "", label));
    item.append(createElement("strong", "", value == null ? "—" : value));
    return item;
  }));
}

function rankingProducts() {
  return dashboardData.rankings[activeRanking];
}

function updateOptionalColumns() {
  document.querySelectorAll("[data-column-toggle]").forEach((toggle) => {
    document.querySelectorAll(`[data-column="${toggle.value}"]`).forEach((cell) => {
      cell.hidden = !toggle.checked;
    });
  });
}

function createMetricCell(column, text) {
  const cell = createElement("td", "number center-col", text);
  cell.dataset.column = column;
  return cell;
}

function renderTable() {
  const products = rankingProducts();

  const tbody = $("#product-rows");
  if (!products.length) {
    const row = document.createElement("tr");
    const cell = createElement("td", "number", "No listings are available for this ranking.");
    cell.colSpan = 8 + [...document.querySelectorAll("[data-column-toggle]")]
      .filter((toggle) => toggle.checked).length;
    row.append(cell);
    tbody.replaceChildren(row);
    updateOptionalColumns();
    return;
  }

  tbody.replaceChildren(...products.map((product) => {
    const row = document.createElement("tr");

    const sourceUrl = safeSourceUrl(product.source_url);
    const imageCell = document.createElement("td");
    imageCell.className = "product-image-cell";
    const imageUrl = safeSourceUrl(product.image_url);
    if (imageUrl) {
      const image = createElement("img", "product-image", null);
      image.src = imageUrl;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        imageCell.replaceChildren(createElement("span", "product-image-placeholder", ""));
      }, { once: true });
      if (sourceUrl) {
        const imageLink = createElement("a", "product-image-link", null);
        imageLink.href = sourceUrl;
        imageLink.target = "_blank";
        imageLink.rel = "noopener";
        imageLink.setAttribute("aria-label", `View ${productLabel(product)}`);
        imageLink.append(image);
        imageCell.append(imageLink);
      } else {
        imageCell.append(image);
      }
    } else {
      imageCell.append(createElement("span", "product-image-placeholder", ""));
    }

    const nameCell = document.createElement("td");
    const name = sourceUrl
      ? createElement("a", "product-name", productLabel(product))
      : createElement("span", "product-name", productLabel(product));
    if (sourceUrl) {
      name.href = sourceUrl;
      name.target = "_blank";
      name.rel = "noopener";
    }
    nameCell.append(name);
    if (product.brand_name) nameCell.append(createElement("span", "brand-name", product.brand_name));

    row.append(imageCell, nameCell);
    row.append(createElement("td", "center-col", product.retailer_name ?? "—"));
    row.append(createElement("td", "number center-col", formatCurrency(product.price)));
    row.append(createElement("td", "number center-col", formatNumber(product.energy_kcal)));
    row.append(createElement("td", "number center-col", `${formatNumber(product.protein_g)} g`));
    row.append(createMetricCell("cost-per-100-kcal", formatCurrency(product.cost_per_100_kcal)));
    row.append(createMetricCell("protein-per-100-kcal", `${formatNumber(product.protein_g_per_100_kcal)} g`));
    row.append(createMetricCell("cost-per-100g-protein", formatCurrency(product.cost_per_100g_protein)));
    row.append(createElement("td", "number score-col center-col", formatNumber(product.value_score)));
    row.append(createElement("td", "number score-col center-col", formatNumber(product.protein_score)));
    return row;
  }));
  updateOptionalColumns();
}

document.querySelectorAll("[data-column-toggle]").forEach((toggle) => {
  toggle.addEventListener("change", renderTable);
});

$("#value-measure").addEventListener("change", renderRetailerChart);
const tabs = [...document.querySelectorAll(".tab")];

function activateTab(tab, moveFocus = false) {
  tabs.forEach(item => {
    const isActive = item === tab;
    item.classList.toggle("active", isActive);
    item.setAttribute("aria-selected", String(isActive));
    item.tabIndex = isActive ? 0 : -1;
  });
  activeRanking = tab.dataset.ranking;
  $("#ranking-panel").setAttribute("aria-labelledby", tab.id);
  renderTable();
  if (moveFocus) tab.focus();
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab));
});

document.addEventListener("keydown", (event) => {
  const activeElement = document.activeElement;
  const currentTab = activeElement?.closest("[role='tab']") ||
    (activeElement === document.body ? tabs.find((tab) => tab.getAttribute("aria-selected") === "true") : null);
  if (!currentTab || !tabs.includes(currentTab)) return;

  const currentIndex = tabs.indexOf(currentTab);
  let nextIndex = null;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
  if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = tabs.length - 1;
  if (nextIndex !== null) {
    event.preventDefault();
    activateTab(tabs[nextIndex], true);
  }
});

loadData();
