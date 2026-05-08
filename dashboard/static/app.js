const state = {
  snapshot: null,
  styleConfig: {},
  styleOptions: {},
  styleRules: {},
  styleTitles: {},
  apiRendered: false,
  refreshing: false,
  selectedRunId: "",
  traceCache: {},
  traceLoadingRunId: "",
};

const dimensionTitles = {
  investment_period: "投资周期",
  risk_preference: "风险偏好",
  stock_selection: "选股偏好",
  trading_frequency: "交易频率",
  decision_basis: "决策依据",
  position_style: "仓位风格",
  take_profit_stop_loss: "止盈止损",
  market_adaptability: "市场适应",
};

const defaultStyleRules = {
  investment_period: {
    min_items: 1,
    max_items: 1,
    reason: "投资周期是主时间框架，只能单选，避免短线/波段/长线同时驱动决策。",
  },
  risk_preference: {
    min_items: 1,
    max_items: 1,
    reason: "风险偏好是账户级风险基调，只能单选。",
  },
  stock_selection: {
    min_items: 1,
    max_items: 4,
    reason: "选股偏好可以组合，但不宜过多，否则筛选标准会变得发散。",
    conflicts: [["value", "low_reversal"]],
  },
  trading_frequency: {
    min_items: 1,
    max_items: 1,
    reason: "交易频率是运行节奏，只能单选。",
  },
  decision_basis: {
    min_items: 1,
    max_items: 2,
    reason: "决策依据最多保留一个主框架加一个补充优先级。",
    conflicts: [["fundamental_first", "technical_first", "fund_flow_first", "balanced"]],
  },
  position_style: {
    min_items: 1,
    max_items: 3,
    reason: "仓位风格可以组合，例如轻仓试探 + 分批建仓，但互斥风格不能同时出现。",
    conflicts: [["concentrated", "diversified"]],
  },
  take_profit_stop_loss: {
    min_items: 1,
    max_items: 3,
    reason: "止盈止损可以组合，但严格止损和宽止损不能同时作为默认风格。",
    conflicts: [["strict_stop_loss", "wide_stop_loss"]],
  },
  market_adaptability: {
    min_items: 1,
    max_items: 3,
    reason: "市场适应性可以组合，例如防守 + 趋势跟随，但不宜过多。",
  },
};

const $ = (id) => document.getElementById(id);

const pageMeta = {
  console: { eyebrow: "Console", title: "主控制台" },
  trace: { eyebrow: "Trace", title: "调用轨迹" },
  style: { eyebrow: "Style", title: "投资风格配置" },
  api: { eyebrow: "API", title: "API 配置" },
};

function cloneData(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function text(id, value) {
  const node = $(id);
  if (node) node.textContent = value ?? "--";
}

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(number);
}

function formatNumber(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: digits,
  }).format(number);
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${(number * 100).toFixed(2)}%`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function shortText(value, fallback = "--") {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) return value.join("、") || fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function setMessage(id, message, type = "") {
  const node = $(id);
  if (!node) return;
  node.className = `inline-message ${type}`.trim();
  node.textContent = message || "";
}

function setLive(ok) {
  const node = $("liveStatus");
  if (!node) return;
  node.textContent = ok ? "LIVE" : "OFFLINE";
  node.classList.toggle("offline", !ok);
}

function switchPage(page) {
  const target = pageMeta[page] ? page : "console";
  document.querySelectorAll(".page-view").forEach((node) => {
    node.classList.toggle("active", node.id === `page-${target}`);
  });
  document.querySelectorAll(".nav-item").forEach((node) => {
    node.classList.toggle("active", node.dataset.page === target);
  });
  text("pageEyebrow", pageMeta[target].eyebrow);
  text("pageTitle", pageMeta[target].title);
}

function tagClass(value) {
  const lower = String(value || "").toLowerCase();
  if (["failed", "error", "false", "high"].includes(lower)) return "failed";
  if (["success", "true", "low"].includes(lower)) return "success";
  return "";
}

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function emptyRow(colspan, label = "暂无数据") {
  const tr = document.createElement("tr");
  tr.className = "empty-row";
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.textContent = label;
  tr.appendChild(td);
  return tr;
}

function cell(value, className = "") {
  const td = document.createElement("td");
  td.textContent = shortText(value);
  if (className) td.className = className;
  td.title = td.textContent;
  return td;
}

function renderTable(bodyId, rows, columns, emptyLabel) {
  const body = $(bodyId);
  if (!body) return;
  clearNode(body);

  if (!rows || rows.length === 0) {
    body.appendChild(emptyRow(columns.length, emptyLabel));
    return;
  }

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const value = column.value(row);
      const className = column.className ? column.className(row, value) : "";
      tr.appendChild(cell(value, className));
    });
    body.appendChild(tr);
  });
}

function renderAccount(data) {
  const account = data.account || {};
  const risk = account.risk || {};
  const totalAsset = Number(account.total_asset) || 0;
  const marketValue = Number(account.market_value) || 0;
  const availableCash = Number(account.available_cash ?? account.cash) || 0;
  const allocationBase = Math.max(totalAsset, marketValue + availableCash, 1);
  const marketPct = clamp((marketValue / allocationBase) * 100, 0, 100);
  const positionRatio = totalAsset > 0 ? marketValue / totalAsset : 0;

  text("accountMode", account.mode || "--");
  text("totalAsset", formatMoney(totalAsset));
  text("availableCash", formatMoney(availableCash));
  text("marketValue", formatMoney(marketValue));
  text("positionCount", account.position_count ?? data.metrics?.holdings_count ?? 0);
  text("assetPositionRatio", formatPercent(positionRatio));
  text("assetMarketLegend", `${formatMoney(marketValue)} · ${marketPct.toFixed(1)}%`);
  text("assetCashLegend", `${formatMoney(availableCash)} · ${(100 - marketPct).toFixed(1)}%`);
  text("assetRiskLegend", risk.stop_trading ? "停止交易" : "正常");
  text("maxPositionRatio", `总仓位 ${formatPercent(risk.max_position_ratio)}`);
  text("maxSingleStockRatio", `单票 ${formatPercent(risk.max_single_stock_ratio)}`);
  text("maxDailyTrades", `日交易 ${risk.max_daily_trades ?? "--"}`);
  text("stopTrading", risk.stop_trading ? "风控 停止交易" : "风控 正常");

  const assetPie = $("assetPie");
  if (assetPie) {
    assetPie.style.background = `conic-gradient(var(--accent) 0 ${marketPct}%, var(--surface-3) ${marketPct}% 100%)`;
  }
}

function renderMarket(data) {
  const market = data.market || {};
  text("marketRisk", `${market.market_view || "unknown"} / ${market.risk_level || "unknown"}`);
  text("marketSummary", market.summary || "暂无市场摘要");

  const chips = $("marketChips");
  clearNode(chips);
  const groups = [
    ["热点", market.hot_topics],
    ["关注", market.watch_sectors],
    ["回避", market.avoid_sectors],
    ["事件", market.key_events],
  ];

  groups.forEach(([label, values]) => {
    (Array.isArray(values) ? values : []).slice(0, 6).forEach((value) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = `${label}: ${shortText(value)}`;
      chip.title = chip.textContent;
      chips.appendChild(chip);
    });
  });

  if (!chips.childElementCount) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = "暂无标签";
    chips.appendChild(chip);
  }
}

function renderPools(data) {
  const metrics = data.metrics || {};
  text("holdingsCount", `${metrics.holdings_count ?? data.holdings?.length ?? 0} 条`);
  text("stocksCount", `${metrics.strategies_count ?? data.stock_pool?.length ?? 0} 条`);
  text("candidatesCount", `${metrics.candidates_count ?? data.candidates?.length ?? 0} 条`);
  renderHoldingsOverview(data.holdings || []);

  renderTable(
    "holdingsBody",
    data.holdings || [],
    [
      { value: (row) => row.symbol },
      { value: (row) => row.name },
      { value: (row) => row.count },
      { value: (row) => formatNumber(row.cost_price, 3) },
      { value: (row) => formatNumber(row.current_price, 3) },
      {
        value: (row) => `${formatMoney(row.unrealized_pnl)} / ${formatPercent(row.unrealized_pnl_pct)}`,
        className: (row) => (Number(row.unrealized_pnl) >= 0 ? "positive" : "negative"),
      },
      { value: (row) => row.status },
    ],
    "暂无持仓"
  );

  renderTable(
    "stocksBody",
    data.stock_pool || [],
    [
      { value: (row) => row.symbol },
      { value: (row) => row.name },
      { value: (row) => row.strategy_type || row.strategy_id },
      { value: (row) => row.status },
      { value: (row) => row.priority },
      { value: (row) => row.valid_until },
    ],
    "暂无策略股票"
  );

  renderTable(
    "candidatesBody",
    data.candidates || [],
    [
      { value: (row) => row.symbol },
      { value: (row) => row.name },
      { value: (row) => formatNumber(row.score, 1) },
      { value: (row) => formatNumber(row.current_price, 3) },
      { value: (row) => row.status },
      { value: (row) => row.next_action || row.reason },
    ],
    "暂无候选股票"
  );
}

function holdingColor(index) {
  const colors = ["#20d0a2", "#64a8ff", "#f09b58", "#e86ca9", "#b6df5a", "#7d7cff"];
  return colors[index % colors.length];
}

function renderHoldingsOverview(holdings) {
  const marketTotal = holdings.reduce((sum, item) => sum + (Number(item.market_value) || 0), 0);
  const pnlTotal = holdings.reduce((sum, item) => sum + (Number(item.unrealized_pnl) || 0), 0);
  const largest = holdings.reduce((best, item) => {
    const value = Number(item.market_value) || 0;
    return value > (Number(best?.market_value) || 0) ? item : best;
  }, null);

  text("holdingsMarketTotal", formatMoney(marketTotal));
  text("holdingsPnlTotal", formatMoney(pnlTotal));
  text("largestHolding", largest ? `${largest.name || largest.symbol} · ${formatMoney(largest.market_value)}` : "--");
  text("holdingsPieText", holdings.length ? `${holdings.length} 只` : "空");

  const pnlNode = $("holdingsPnlTotal");
  if (pnlNode) {
    pnlNode.classList.toggle("positive", pnlTotal >= 0);
    pnlNode.classList.toggle("negative", pnlTotal < 0);
  }

  const pie = $("holdingsPie");
  const legend = $("holdingsLegend");
  if (!pie || !legend) return;

  clearNode(legend);

  if (!holdings.length || marketTotal <= 0) {
    pie.style.background = "conic-gradient(var(--surface-3) 0 100%)";
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "暂无持仓分布";
    legend.appendChild(empty);
    return;
  }

  let cursor = 0;
  const segments = holdings.map((item, index) => {
    const value = Number(item.market_value) || 0;
    const percent = marketTotal > 0 ? (value / marketTotal) * 100 : 0;
    const start = cursor;
    const end = cursor + percent;
    cursor = end;
    return `${holdingColor(index)} ${start}% ${end}%`;
  });
  pie.style.background = `conic-gradient(${segments.join(", ")})`;

  holdings.slice(0, 6).forEach((item, index) => {
    const value = Number(item.market_value) || 0;
    const row = document.createElement("div");
    row.innerHTML = `<span class="legend-dot" style="background:${holdingColor(index)}"></span><span>${shortText(item.name || item.symbol)}</span><strong>${formatPercent(value / marketTotal)}</strong>`;
    legend.appendChild(row);
  });
}

function styleRule(dimension) {
  return state.styleRules[dimension] || defaultStyleRules[dimension] || { min_items: 1, max_items: 99, conflicts: [] };
}

function styleTitle(dimension) {
  return state.styleTitles[dimension] || dimensionTitles[dimension] || dimension;
}

function styleDescription(dimension, key) {
  const options = state.styleOptions[dimension] || [];
  const option = options.find((item) => item.key === key);
  return option?.description || key;
}

function selectedInputs(dimension) {
  return [...document.querySelectorAll(`#styleEditor input[data-dimension="${dimension}"]`)].filter((input) => input.checked);
}

function selectedValues(dimension) {
  return selectedInputs(dimension).map((input) => input.value);
}

function conflictGroupFor(rule, key) {
  return (rule.conflicts || []).find((group) => group.includes(key)) || null;
}

function hasSelectedConflict(dimension, key) {
  const rule = styleRule(dimension);
  const group = conflictGroupFor(rule, key);
  if (!group) return false;
  const selected = new Set(selectedValues(dimension));
  return group.some((item) => item !== key && selected.has(item));
}

function setStyleGroupStatus(dimension, message, type = "") {
  const node = document.querySelector(`.style-group[data-dimension="${dimension}"] .style-group-status`);
  if (!node) return;
  node.className = `style-group-status ${type}`.trim();
  node.textContent = message;
}

function updateStyleLimits() {
  Object.keys(state.styleOptions).forEach((dimension) => {
    const rule = styleRule(dimension);
    const min = Number(rule.min_items ?? 1);
    const max = Number(rule.max_items ?? 99);
    const inputs = [...document.querySelectorAll(`#styleEditor input[data-dimension="${dimension}"]`)];
    const selected = selectedValues(dimension);
    const count = selected.length;
    const typeLabel = max === 1 ? "单选" : `至少 ${min} 个，最多 ${max} 个`;
    const statusType = count < min || count > max ? "error" : "";

    setStyleGroupStatus(
      dimension,
      `${typeLabel} · 已选 ${count} 个${rule.reason ? ` · ${rule.reason}` : ""}`,
      statusType
    );

    inputs.forEach((input) => {
      const option = input.closest(".style-option");
      const maxReached = max !== 1 && count >= max && !input.checked;
      const conflictBlocked = max !== 1 && !input.checked && hasSelectedConflict(dimension, input.value);
      input.disabled = maxReached || conflictBlocked;

      option?.classList.toggle("selected", input.checked);
      option?.classList.toggle("disabled", input.disabled);
    });
  });
}

function handleStyleChange(event) {
  const input = event.target;
  const dimension = input.dataset.dimension;
  const rule = styleRule(dimension);
  const min = Number(rule.min_items ?? 1);
  const max = Number(rule.max_items ?? 99);

  if (input.type === "checkbox") {
    if (input.checked) {
      const group = conflictGroupFor(rule, input.value);
      if (group) {
        document.querySelectorAll(`#styleEditor input[data-dimension="${dimension}"]`).forEach((other) => {
          if (other !== input && group.includes(other.value) && other.checked) {
            other.checked = false;
          }
        });
      }

      if (selectedValues(dimension).length > max) {
        input.checked = false;
        setMessage("styleMessage", `${styleTitle(dimension)}最多只能选择 ${max} 个`, "error");
      } else if (group) {
        setMessage("styleMessage", `${styleTitle(dimension)}存在互斥项，已自动保留最新选择`, "");
      }
    } else if (selectedValues(dimension).length < min) {
      input.checked = true;
      setMessage("styleMessage", `${styleTitle(dimension)}至少需要选择 ${min} 个`, "error");
    }
  }

  updateStyleLimits();
}

function renderStyle(style) {
  if (!style) return;
  state.styleConfig = cloneData(style.config || {});
  state.styleOptions = style.options || {};
  state.styleRules = style.rules || {};
  state.styleTitles = style.titles || {};

  const editor = $("styleEditor");
  clearNode(editor);

  Object.entries(state.styleOptions).forEach(([dimension, options]) => {
    const rule = styleRule(dimension);
    const max = Number(rule.max_items ?? 99);
    const selected = new Set(max === 1 ? (state.styleConfig[dimension] || []).slice(0, 1) : state.styleConfig[dimension] || []);
    const group = document.createElement("div");
    group.className = "style-group";
    group.dataset.dimension = dimension;

    const title = document.createElement("div");
    title.className = "style-group-title";
    title.textContent = styleTitle(dimension);
    group.appendChild(title);

    const status = document.createElement("div");
    status.className = "style-group-status";
    group.appendChild(status);

    const optionWrap = document.createElement("div");
    optionWrap.className = "style-options";

    options.forEach((option) => {
      const label = document.createElement("label");
      label.className = "style-option";

      const input = document.createElement("input");
      input.type = max === 1 ? "radio" : "checkbox";
      input.name = `style-${dimension}`;
      input.dataset.dimension = dimension;
      input.value = option.key;
      input.checked = selected.has(option.key);
      input.addEventListener("change", handleStyleChange);

      const span = document.createElement("span");
      span.textContent = option.description;

      label.appendChild(input);
      label.appendChild(span);
      optionWrap.appendChild(label);
    });

    group.appendChild(optionWrap);
    editor.appendChild(group);
  });

  updateStyleLimits();
}

function renderStyleSummary(style) {
  const container = $("styleSummary");
  if (!container || !style) return;

  clearNode(container);
  const config = style.config || {};
  const options = style.options || {};
  const titles = style.titles || {};

  Object.keys(options).forEach((dimension) => {
    const selected = config[dimension] || [];
    const item = document.createElement("div");
    item.className = "style-summary-item";

    const title = document.createElement("strong");
    title.textContent = titles[dimension] || dimensionTitles[dimension] || dimension;

    const body = document.createElement("p");
    body.textContent = selected.length
      ? selected.map((key) => {
          const option = (options[dimension] || []).find((entry) => entry.key === key);
          return option?.description || key;
        }).join(" / ")
      : "未配置";

    item.appendChild(title);
    item.appendChild(body);
    container.appendChild(item);
  });
}

function collectStyleConfig() {
  const config = {};
  document.querySelectorAll("#styleEditor input").forEach((input) => {
    const dimension = input.dataset.dimension;
    if (!config[dimension]) config[dimension] = [];
    if (input.checked) config[dimension].push(input.value);
  });
  return config;
}

function validateStyleConfig(config) {
  for (const dimension of Object.keys(state.styleOptions)) {
    const rule = styleRule(dimension);
    const min = Number(rule.min_items ?? 1);
    const max = Number(rule.max_items ?? 99);
    const selected = config[dimension] || [];

    if (selected.length < min) {
      return `${styleTitle(dimension)}至少需要选择 ${min} 个`;
    }

    if (selected.length > max) {
      return `${styleTitle(dimension)}最多只能选择 ${max} 个`;
    }

    for (const group of rule.conflicts || []) {
      const overlap = selected.filter((item) => group.includes(item));
      if (overlap.length > 1) {
        return `${styleTitle(dimension)}存在互斥选项：${overlap.join("、")}`;
      }
    }
  }

  return "";
}

async function saveStyle() {
  const button = $("saveStyleBtn");
  button.disabled = true;
  setMessage("styleMessage", "保存中...");

  try {
    const config = collectStyleConfig();
    const validationError = validateStyleConfig(config);
    if (validationError) throw new Error(validationError);

    const response = await fetch("/api/investment-style", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || "保存失败");
    state.styleConfig = data.config || state.styleConfig;
    setMessage("styleMessage", `已保存到 ${data.files?.config || "配置文件"}`, "ok");
    await refresh();
  } catch (error) {
    setMessage("styleMessage", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function renderApiConfig(apiConfig, force = false) {
  const form = $("apiConfigForm");
  if (!form || !apiConfig || (state.apiRendered && !force)) return;

  clearNode(form);
  text("envFilePath", apiConfig.env_file || ".env");

  (apiConfig.variables || []).forEach((variable) => {
    const row = document.createElement("label");
    row.className = "api-field";

    const head = document.createElement("div");
    head.className = "api-field-head";

    const title = document.createElement("strong");
    title.textContent = variable.label || variable.key;

    const status = document.createElement("span");
    status.className = `api-status ${variable.configured ? "configured" : "missing"}`;
    status.textContent = variable.configured ? "已配置" : "未配置";

    head.appendChild(title);
    head.appendChild(status);

    const description = document.createElement("p");
    description.textContent = variable.description || "";

    const input = document.createElement("input");
    input.type = variable.secret ? "password" : "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.dataset.key = variable.key;
    input.placeholder = variable.configured
      ? `当前：${variable.masked_value || "已配置"}，留空保留`
      : "请输入配置值";

    row.appendChild(head);
    row.appendChild(description);
    row.appendChild(input);
    form.appendChild(row);
  });

  state.apiRendered = true;
}

function collectApiConfig() {
  const env = {};
  document.querySelectorAll("#apiConfigForm input[data-key]").forEach((input) => {
    const value = input.value.trim();
    if (value) env[input.dataset.key] = value;
  });
  return env;
}

async function saveApiConfig() {
  const button = $("saveApiBtn");
  const env = collectApiConfig();

  if (!Object.keys(env).length) {
    setMessage("apiMessage", "没有输入新值；留空会保留已有配置。", "");
    return;
  }

  button.disabled = true;
  setMessage("apiMessage", "保存中...");

  try {
    const response = await fetch("/api/api-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || "保存失败");
    setMessage("apiMessage", `已更新：${(data.updated || []).join("、")}`, "ok");
    renderApiConfig(data.config, true);
    await refresh();
  } catch (error) {
    setMessage("apiMessage", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function renderManual(data) {
  const manual = data.manual_run || {};
  const running = Boolean(manual.running);
  const active = manual.active || {};
  const status = $("manualStatus");

  if (status) {
    status.textContent = running ? "running" : "idle";
    status.className = `tag ${running ? "running" : ""}`.trim();
  }
  $("runManualBtn").disabled = running;
  renderManualRecentList(manual);

  if (running) {
    setMessage("manualMessage", `正在运行：${active.task || ""}`, "");
  } else if (manual.recent && manual.recent.length && !$("manualMessage").textContent) {
    const latest = manual.recent[manual.recent.length - 1];
    setMessage("manualMessage", `最近一次：${latest.status || "--"} · ${latest.task || ""}`, "");
  }
}

function manualRunStatusText(status) {
  const value = String(status || "").toLowerCase();
  if (value === "running") return "运行中";
  if (value === "success") return "成功";
  if (value === "failed") return "失败";
  return status || "未知";
}

function renderManualRecentList(manual) {
  const list = $("manualRecentList");
  if (!list) return;
  clearNode(list);

  const items = [];
  if (manual.running && manual.active) {
    items.push({ ...manual.active, status: "running" });
  }
  (manual.recent || []).slice().reverse().slice(0, 5).forEach((item) => items.push(item));

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "manual-run-empty";
    empty.textContent = "暂无人工指令记录";
    list.appendChild(empty);
    return;
  }

  items.forEach((run) => {
    const item = document.createElement("div");
    item.className = `manual-run-item ${tagClass(run.status)}`.trim();

    const head = document.createElement("div");
    head.className = "manual-run-head";
    const status = document.createElement("strong");
    status.textContent = manualRunStatusText(run.status);
    const time = document.createElement("span");
    time.textContent = run.ended_at || run.started_at || "--";
    head.appendChild(status);
    head.appendChild(time);

    const task = document.createElement("p");
    task.textContent = run.task || "未记录指令";

    const meta = document.createElement("small");
    const exitCode = run.exit_code === undefined || run.exit_code === null ? "--" : run.exit_code;
    meta.textContent = `steps ${run.max_steps || "--"} · exit ${exitCode}`;

    item.appendChild(head);
    item.appendChild(task);
    item.appendChild(meta);
    list.appendChild(item);
  });
}

async function runManual() {
  const task = $("manualTask").value.trim();
  const maxSteps = Number($("maxSteps").value || 50);
  if (!task) {
    setMessage("manualMessage", "请输入人工指令", "error");
    return;
  }

  $("runManualBtn").disabled = true;
  setMessage("manualMessage", "已提交，等待 Agent 执行...");

  try {
    const response = await fetch("/api/manual-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, max_steps: maxSteps }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || "提交失败");
    setMessage("manualMessage", `已启动：${data.run.id}`, "ok");
    await refresh();
  } catch (error) {
    setMessage("manualMessage", error.message, "error");
    $("runManualBtn").disabled = false;
  }
}

function renderSystem(data) {
  const scheduler = data.scheduler || {};
  const initialization = data.initialization || {};
  const schedulerRunning = Boolean(scheduler.running);
  const initializationRunning = Boolean(initialization.running);
  const latestInit = initialization.active || (initialization.recent || []).slice(-1)[0] || null;
  const badge = $("schedulerBadge");

  if (badge) {
    badge.textContent = schedulerRunning ? "running" : "stopped";
    badge.className = `tag ${schedulerRunning ? "success" : "failed"}`;
  }

  text("schedulerPid", schedulerRunning ? `PID ${scheduler.pid}` : "未运行");
  text(
    "schedulerMeta",
    schedulerRunning
      ? `启动于 ${scheduler.started_at || "--"} · ${scheduler.python || scheduler.config_file || "--"}`
      : `Python ${scheduler.python || "--"}`
  );
  text("initializationStatus", initializationRunning ? "初始化中" : latestInit?.status || "待命");
  text(
    "initializationMeta",
    initializationRunning
      ? `开始于 ${initialization.active?.started_at || "--"}`
      : latestInit
        ? `最近一次 ${latestInit.ended_at || latestInit.started_at || "--"} · ${latestInit.exit_code ?? "--"}`
        : "清空运行数据并重置账户/市场状态"
  );

  const logTail = $("schedulerLogTail");
  if (logTail) {
    logTail.textContent = (scheduler.log_tail || []).join("\n") || "暂无 scheduler 日志";
  }

  $("startSchedulerBtn").disabled = schedulerRunning || initializationRunning;
  $("stopSchedulerBtn").disabled = !schedulerRunning || initializationRunning;
  $("initializeBtn").disabled = initializationRunning;
}

async function postControl(path, pendingMessage) {
  setMessage("systemMessage", pendingMessage);

  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || "操作失败");
    setMessage("systemMessage", data.message || "操作完成", "ok");
    await refresh();
  } catch (error) {
    setMessage("systemMessage", error.message, "error");
  }
}

function startScheduler() {
  postControl("/api/scheduler/start", "正在启动 scheduler...");
}

function stopScheduler() {
  postControl("/api/scheduler/stop", "正在停止 scheduler...");
}

function initializeWorkspace() {
  const ok = window.confirm("初始化会清空 pools/logs/memory/reports，并重置账户和市场状态。确定继续？");
  if (!ok) return;
  postControl("/api/initialize-workspace", "正在初始化 workspace...");
}

function runStatusText(run) {
  if (run.success === true || String(run.success).toLowerCase() === "true") return "成功";
  if (run.success === false || String(run.success).toLowerCase() === "false") return "失败";
  return "未知";
}

function createRunCard(run, options = {}) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = `run-item run-card ${tagClass(run.success)}${options.active ? " active" : ""}`.trim();
  item.dataset.runId = run.run_id || "";
  item.title = run.run_id || "";
  item.addEventListener("click", () => openTrace(run.run_id));

  const title = document.createElement("strong");
  title.textContent = run.run_id || "--";

  const meta = document.createElement("p");
  meta.textContent = `${run.mode || "--"} · ${run.phase || "--"} · ${runStatusText(run)} · ${run.steps || 0} steps · ${run.tool_call_count || 0} tools`;

  const time = document.createElement("p");
  time.textContent = run.timestamp || "暂无时间";

  const summary = document.createElement("p");
  summary.textContent = run.summary || "暂无摘要";

  item.appendChild(title);
  item.appendChild(meta);
  item.appendChild(time);
  item.appendChild(summary);
  return item;
}

function renderCallHistory(data) {
  const logs = data.logs || {};
  const runs = logs.run_dirs || [];
  const list = $("callHistoryList");
  clearNode(list);
  text("callHistoryCount", `${runs.length} 条`);

  if (!runs.length) {
    const item = document.createElement("div");
    item.className = "run-item";
    item.innerHTML = "<strong>暂无调用记录</strong><p>等待主 Agent 产生运行日志</p>";
    list.appendChild(item);
    return;
  }

  runs.forEach((run) => {
    list.appendChild(createRunCard(run, { active: run.run_id === state.selectedRunId }));
  });
}

function renderTraceRunList(data) {
  const list = $("traceRunList");
  if (!list) return;
  const runs = data.logs?.run_dirs || [];
  clearNode(list);

  if (!runs.length) {
    const item = document.createElement("div");
    item.className = "run-item";
    item.innerHTML = "<strong>暂无调用记录</strong><p>等待主 Agent 产生运行日志</p>";
    list.appendChild(item);
    return;
  }

  runs.forEach((run) => {
    list.appendChild(createRunCard(run, { active: run.run_id === state.selectedRunId }));
  });
}

function traceTitle(step) {
  if (step.kind === "tool") return `${step.tool || "tool"} · ${step.success ? "success" : "failed"}`;
  if (step.type === "tool_call") return `tool_call · ${step.tool || "tool"}`;
  if (step.type === "final") return "final · 本轮总结";
  if (step.type === "error") return "error · 协议重试";
  return step.type || "model";
}

function traceBody(step) {
  if (step.kind === "tool") {
    return firstTraceLine(step.body || step.error || step.path || step.reason || `exit_code: ${step.exit_code ?? "--"}`);
  }
  return step.body || step.summary || step.next_action || step.reason || step.raw_preview || "暂无内容";
}

function firstTraceLine(value, limit = 220) {
  const line = String(value || "")
    .replace(/\r/g, "")
    .split("\n")
    .map((item) => item.trim())
    .find(Boolean) || "暂无返回";
  return line.length > limit ? `${line.slice(0, limit).trim()}...` : line;
}

function traceValueText(value) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function createTraceArgValue(value) {
  const box = document.createElement("div");
  box.className = "trace-arg-value";

  if (Array.isArray(value)) {
    if (!value.length) {
      box.textContent = "--";
      return box;
    }
    value.slice(0, 8).forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "trace-arg-chip";
      chip.textContent = traceValueText(item);
      box.appendChild(chip);
    });
    if (value.length > 8) {
      const more = document.createElement("span");
      more.className = "trace-arg-chip muted";
      more.textContent = `+${value.length - 8}`;
      box.appendChild(more);
    }
    return box;
  }

  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) {
      box.textContent = "--";
      return box;
    }
    entries.slice(0, 6).forEach(([key, nestedValue]) => {
      const chip = document.createElement("span");
      chip.className = "trace-arg-chip pair";
      const label = document.createElement("span");
      label.textContent = key;
      const content = document.createElement("b");
      content.textContent = traceValueText(nestedValue);
      chip.appendChild(label);
      chip.appendChild(content);
      box.appendChild(chip);
    });
    if (entries.length > 6) {
      const more = document.createElement("span");
      more.className = "trace-arg-chip muted";
      more.textContent = `+${entries.length - 6}`;
      box.appendChild(more);
    }
    return box;
  }

  box.textContent = traceValueText(value);
  return box;
}

function createTraceArgsPanel(args) {
  if (!args || !Object.keys(args).length) return null;

  const panel = document.createElement("div");
  panel.className = "trace-args";

  const head = document.createElement("div");
  head.className = "trace-args-head";
  const title = document.createElement("span");
  title.textContent = "参数";
  const count = document.createElement("em");
  count.textContent = `${Object.keys(args).length}`;
  head.appendChild(title);
  head.appendChild(count);
  panel.appendChild(head);

  Object.entries(args).forEach(([key, value]) => {
    const row = document.createElement("div");
    row.className = "trace-arg-row";
    const label = document.createElement("span");
    label.className = "trace-arg-key";
    label.textContent = key;
    row.appendChild(label);
    row.appendChild(createTraceArgValue(value));
    panel.appendChild(row);
  });

  return panel;
}

function normalizeFinalItems(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter((item) => item !== undefined && item !== null && item !== "");
  return [value];
}

function finalItemTitle(item) {
  if (!item || typeof item !== "object") return "";
  return item.decision || item.action || item.todo || item.tool || item.title || "";
}

function finalItemDetail(item) {
  if (item === undefined || item === null || item === "") return "";
  if (typeof item !== "object") return String(item);

  const detail = item.reason || item.result || item.summary || item.query || item.path || item.content;
  if (detail) return traceValueText(detail);

  const title = finalItemTitle(item);
  const pairs = Object.entries(item)
    .filter(([key, value]) => value !== undefined && value !== null && value !== "" && value !== title && !["decision", "action", "todo", "tool", "title"].includes(key))
    .map(([key, value]) => `${key}: ${traceValueText(value)}`);
  return pairs.join(" · ");
}

function createFinalSection(title, value) {
  const items = normalizeFinalItems(value);
  if (!items.length) return null;

  const section = document.createElement("div");
  section.className = "trace-final-section";
  const heading = document.createElement("span");
  heading.className = "trace-final-heading";
  heading.textContent = title;
  section.appendChild(heading);

  const list = document.createElement("div");
  list.className = "trace-final-list";
  items.slice(0, 6).forEach((item) => {
    const row = document.createElement("div");
    row.className = "trace-final-row";
    const titleText = finalItemTitle(item);
    const detailText = finalItemDetail(item);

    if (titleText) {
      const strong = document.createElement("strong");
      strong.textContent = titleText;
      row.appendChild(strong);
    }

    const detail = document.createElement("p");
    detail.textContent = detailText || traceValueText(item);
    row.appendChild(detail);
    list.appendChild(row);
  });

  if (items.length > 6) {
    const more = document.createElement("em");
    more.className = "trace-final-more";
    more.textContent = `还有 ${items.length - 6} 项`;
    list.appendChild(more);
  }

  section.appendChild(list);
  return section;
}

function createTraceFinalPanel(step) {
  const panel = document.createElement("div");
  panel.className = "trace-final-panel";

  const summary = document.createElement("div");
  summary.className = "trace-final-summary";
  const label = document.createElement("span");
  label.textContent = "总结";
  const textNode = document.createElement("p");
  textNode.textContent = step.summary || firstTraceLine(step.body, 360);
  summary.appendChild(label);
  summary.appendChild(textNode);
  panel.appendChild(summary);

  [
    ["执行动作", step.actions],
    ["关键判断", step.decisions],
    ["后续事项", step.next_todos],
    ["工具链路", step.tool_calls],
  ].forEach(([title, value]) => {
    const section = createFinalSection(title, value);
    if (section) panel.appendChild(section);
  });

  return panel;
}

function renderTraceSummary(trace) {
  const summary = $("traceSummary");
  if (!summary) return;
  clearNode(summary);

  const run = trace?.run || {};
  const fields = [
    ["Run ID", run.run_id || state.selectedRunId || "--"],
    ["模式", run.mode || "--"],
    ["阶段", run.phase || "--"],
    ["状态", runStatusText(run)],
    ["步骤", `${run.steps || trace?.steps?.length || 0}`],
    ["工具调用", `${run.tool_call_count || 0}`],
  ];

  fields.forEach(([label, value]) => {
    const item = document.createElement("div");
    item.className = "trace-summary-item";
    const key = document.createElement("span");
    key.textContent = label;
    const val = document.createElement("strong");
    val.textContent = value;
    item.appendChild(key);
    item.appendChild(val);
    summary.appendChild(item);
  });
}

function renderTraceDetail(trace) {
  renderTraceSummary(trace);
  const steps = trace?.steps || [];
  const list = $("traceList");
  clearNode(list);
  text("selectedRunBadge", trace?.run?.run_id || state.selectedRunId || "--");

  if (!steps.length) {
    const item = document.createElement("div");
    item.className = "trace-item";
    item.innerHTML = "<strong>暂无步骤</strong><p>最新运行还没有可展示的步骤</p>";
    list.appendChild(item);
    return;
  }

  steps.slice().reverse().forEach((step) => {
    const item = document.createElement("div");
    const status = step.kind === "tool" ? (step.success ? "success" : "failed") : "";
    const typeClass = step.kind === "model" && step.type ? step.type : "";
    item.className = `trace-item ${step.kind || "model"} ${typeClass} ${status}`.trim();

    const meta = document.createElement("div");
    meta.className = "trace-meta";
    [step.kind, `step ${step.step ?? "--"}`, step.timestamp].filter(Boolean).forEach((value) => {
      const chip = document.createElement("span");
      chip.textContent = value;
      meta.appendChild(chip);
    });

    const title = document.createElement("strong");
    title.textContent = traceTitle(step);

    const body = document.createElement("p");
    body.textContent = traceBody(step);

    item.appendChild(meta);
    item.appendChild(title);
    if (step.kind === "model" && step.type === "final") {
      item.appendChild(createTraceFinalPanel(step));
    } else {
      item.appendChild(body);
    }
    if (step.kind === "model" && step.type === "tool_call") {
      const argsPanel = createTraceArgsPanel(step.args);
      if (argsPanel) item.appendChild(argsPanel);
    }
    list.appendChild(item);
  });
}

function renderTracePage() {
  if (!state.snapshot) return;
  const runs = state.snapshot.logs?.run_dirs || [];
  const selectedStillExists = runs.some((run) => run.run_id === state.selectedRunId);
  if (state.selectedRunId && !selectedStillExists) {
    state.selectedRunId = runs[0]?.run_id || "";
  }

  renderTraceRunList(state.snapshot);

  if (!state.selectedRunId) {
    clearNode($("traceSummary"));
    clearNode($("traceList"));
    text("selectedRunBadge", "--");
    const item = document.createElement("div");
    item.className = "trace-item";
    item.innerHTML = "<strong>暂无选中的调用</strong><p>从调用历史中选择一条记录</p>";
    $("traceList").appendChild(item);
    return;
  }

  const cached = state.traceCache[state.selectedRunId];
  if (cached) {
    renderTraceDetail(cached);
    return;
  }

  clearNode($("traceSummary"));
  clearNode($("traceList"));
  text("selectedRunBadge", state.selectedRunId);
  const item = document.createElement("div");
  item.className = "trace-item";
  item.innerHTML = "<strong>加载中</strong><p>正在读取调用轨迹</p>";
  $("traceList").appendChild(item);
}

async function loadTrace(runId) {
  if (!runId || state.traceCache[runId] || state.traceLoadingRunId === runId) return;
  state.traceLoadingRunId = runId;

  try {
    const response = await fetch(`/api/trace?run_id=${encodeURIComponent(runId)}`, { cache: "no-store" });
    const trace = await response.json();
    if (!response.ok || trace.success === false) throw new Error(trace.error || "读取轨迹失败");
    state.traceCache[runId] = trace;
    if (state.selectedRunId === runId) renderTraceDetail(trace);
  } catch (error) {
    if (state.selectedRunId !== runId) return;
    clearNode($("traceSummary"));
    clearNode($("traceList"));
    const item = document.createElement("div");
    item.className = "trace-item failed";
    const title = document.createElement("strong");
    title.textContent = "读取失败";
    const body = document.createElement("p");
    body.textContent = error.message;
    item.appendChild(title);
    item.appendChild(body);
    $("traceList").appendChild(item);
  } finally {
    if (state.traceLoadingRunId === runId) state.traceLoadingRunId = "";
  }
}

function openTrace(runId) {
  if (!runId) return;
  state.selectedRunId = runId;
  switchPage("trace");
  renderCallHistory(state.snapshot || {});
  renderTracePage();
  loadTrace(runId);
}

function ensureTraceSelection() {
  if (state.selectedRunId) {
    renderTracePage();
    loadTrace(state.selectedRunId);
    return;
  }

  const first = state.snapshot?.logs?.run_dirs?.[0];
  if (first?.run_id) {
    openTrace(first.run_id);
  } else {
    renderTracePage();
  }
}

function render(data) {
  state.snapshot = data;
  text("lastUpdated", `更新 ${data.updated_at || "--"}`);
  renderAccount(data);
  renderMarket(data);
  renderPools(data);
  renderStyleSummary(data.style);
  renderApiConfig(data.api_config);
  renderManual(data);
  renderSystem(data);
  if (state.selectedRunId) {
    const stillExists = (data.logs?.run_dirs || []).some((run) => run.run_id === state.selectedRunId);
    if (!stillExists) {
      state.selectedRunId = data.logs?.run_dirs?.[0]?.run_id || "";
    }
  }
  renderCallHistory(data);
  renderTraceRunList(data);

  if (!Object.keys(state.styleOptions).length) {
    renderStyle(data.style);
  }

  if (document.querySelector("#page-trace.active")) {
    renderTracePage();
  }
}

async function refresh() {
  if (state.refreshing) return;
  state.refreshing = true;

  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    setLive(true);
    render(data);
  } catch (error) {
    setLive(false);
    setMessage("manualMessage", "Dashboard 服务未连接。请在项目根目录运行：python dashboard/server.py 8787", "error");
    setMessage("styleMessage", "保存风格需要 dashboard 服务在线。", "error");
    setMessage("apiMessage", "保存 API 配置需要 dashboard 服务在线。", "error");
    console.error(error);
  } finally {
    state.refreshing = false;
  }
}

function bindEvents() {
  $("refreshBtn").addEventListener("click", () => refresh());
  $("saveStyleBtn").addEventListener("click", () => saveStyle());
  $("saveApiBtn").addEventListener("click", () => saveApiConfig());
  $("runManualBtn").addEventListener("click", () => runManual());
  $("startSchedulerBtn").addEventListener("click", () => startScheduler());
  $("stopSchedulerBtn").addEventListener("click", () => stopScheduler());
  $("initializeBtn").addEventListener("click", () => initializeWorkspace());
  document.querySelectorAll(".nav-item, .nav-shortcut").forEach((button) => {
    button.addEventListener("click", () => {
      switchPage(button.dataset.page);
      if (button.dataset.page === "trace") ensureTraceSelection();
    });
  });
}

bindEvents();
refresh();
setInterval(refresh, 3000);
