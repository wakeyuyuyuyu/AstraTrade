const state = {
  snapshot: null,
  styleConfig: {},
  styleOptions: {},
  styleRules: {},
  styleTitles: {},
  apiRendered: false,
  schedulerConfigRendered: false,
  refreshing: false,
  selectedRunId: "",
  traceCache: {},
  traceLoadingRunId: "",
  workstreamFallbackRunId: "",
  workstreamFallbackLoading: false,
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
  "scheduler-config": { eyebrow: "Scheduler", title: "自动触发配置" },
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

const accountModeLabels = {
  active: "运行中",
  initialization: "初始化",
  paper: "模拟盘",
  live: "实盘",
  paused: "已暂停",
  stopped: "已停止",
};

const marketViewLabels = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
  warm: "偏暖",
  weak: "偏弱",
  unknown: "未知",
};

const marketRiskLabels = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  unknown: "未知风险",
};

const marketSentimentLabels = {
  bullish: "乐观",
  positive: "偏暖",
  warm: "偏暖",
  neutral: "中性",
  cautious: "谨慎",
  weak: "偏弱",
  bearish: "悲观",
  negative: "悲观",
  unknown: "未知",
};

function compactDateTime(value) {
  const raw = String(value || "").trim();
  if (!raw) return "--";
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (match) return `${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
  return raw;
}

function parseDateTime(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) return null;
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6] || 0)
  );
  return Number.isFinite(date.getTime()) ? date : null;
}

function latestDateTime(values) {
  return values.map(parseDateTime).filter(Boolean).sort((a, b) => b.getTime() - a.getTime())[0] || null;
}

function formatParsedDateTime(date) {
  if (!date) return "--";
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function isStale(date, maxAgeMinutes) {
  if (!date) return true;
  return Date.now() - date.getTime() > maxAgeMinutes * 60 * 1000;
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

function dailyTradeCount(data, day) {
  const account = data.account || {};
  const explicit = account.daily_trades ?? account.daily_trade_count ?? account.today_trades;
  if (Number.isFinite(Number(explicit))) return Number(explicit);

  const trades = data.logs?.trades || [];
  return trades.filter((trade) => {
    const value = String(trade.timestamp || trade.created_at || trade.time || trade.date || "");
    return value.startsWith(day);
  }).length;
}

const inactiveHoldingStatuses = new Set(["sold", "closed", "cleared", "removed", "已卖出", "已清仓", "清仓"]);

function holdingQuantity(item) {
  return Number(item?.count ?? item?.quantity ?? item?.shares) || 0;
}

function holdingMarketValue(item) {
  const marketValue = Number(item?.market_value);
  if (Number.isFinite(marketValue) && marketValue !== 0) return marketValue;

  const price = Number(item?.current_price ?? item?.price) || 0;
  return holdingQuantity(item) * price;
}

function activeHoldings(holdings) {
  return (holdings || []).filter((item) => {
    const status = String(item?.status || "holding").trim().toLowerCase();
    if (inactiveHoldingStatuses.has(status)) return false;
    return holdingQuantity(item) > 0 || holdingMarketValue(item) > 0;
  });
}

function setTag(id, label, className = "", title = "") {
  const node = $(id);
  if (!node) return;
  node.textContent = label || "--";
  node.className = `tag ${className}`.trim();
  node.title = title || "";
}

function accountStatus(account, holdings) {
  const mode = String(account.mode || "").toLowerCase();
  const updatedAt = latestDateTime([
    account.updated_at,
    ...holdings.map((item) => item.updated_at),
  ]);

  if (account.risk?.stop_trading) {
    return {
      label: "风控停止",
      className: "failed",
      title: "账户风控 stop_trading 已触发",
    };
  }

  if (isStale(updatedAt, 90)) {
    return {
      label: "待同步",
      className: "running",
      title: "账户或持仓超过 90 分钟未同步",
    };
  }

  return {
    label: accountModeLabels[mode] || account.mode || "账户在线",
    className: mode === "initialization" ? "running" : "success",
    title: updatedAt ? `最近同步 ${formatParsedDateTime(updatedAt)}` : "",
  };
}

function marketStatus(market) {
  const view = String(market.market_view || "unknown").toLowerCase();
  const risk = String(market.risk_level || "unknown").toLowerCase();
  const updatedAt = parseDateTime(market.updated_at);

  if (isStale(updatedAt, 240)) {
    return {
      label: "市场待刷新",
      className: "running",
      title: "市场状态超过 4 小时未更新",
    };
  }

  return {
    label: `${marketViewLabels[view] || market.market_view || "未知"} / ${marketRiskLabels[risk] || market.risk_level || "未知风险"}`,
    className: risk === "high" ? "failed" : risk === "low" ? "success" : "running",
    title: updatedAt ? `市场状态 ${formatParsedDateTime(updatedAt)} 更新` : "",
  };
}

function riskClass(usage, hardStop = false) {
  if (hardStop) return "danger";
  if (!Number.isFinite(usage)) return "idle";
  if (usage >= 1) return "danger";
  if (usage >= 0.8) return "warn";
  return "ok";
}

function renderRiskPill(id, config) {
  const node = $(id);
  if (!node) return;
  clearNode(node);

  const usage = Number(config.usage);
  const className = riskClass(usage, config.hardStop);
  node.className = `risk-pill ${className}`;
  node.title = config.detail || "";

  const label = document.createElement("span");
  label.className = "risk-label";
  label.textContent = config.label;

  const value = document.createElement("strong");
  value.textContent = config.value;

  const meta = document.createElement("small");
  meta.textContent = config.meta;

  const bar = document.createElement("i");
  const fill = document.createElement("b");
  fill.style.width = `${clamp(Number.isFinite(usage) ? usage * 100 : 0, 0, 100)}%`;
  bar.appendChild(fill);

  node.appendChild(label);
  node.appendChild(value);
  node.appendChild(meta);
  node.appendChild(bar);
}

function renderAccount(data) {
  const account = data.account || {};
  const risk = account.risk || {};
  const holdings = activeHoldings(data.holdings || []);
  const holdingsMarketValue = holdings.reduce((sum, item) => sum + holdingMarketValue(item), 0);
  const accountTotalAsset = Number(account.total_asset) || 0;
  const accountCash = Number(account.available_cash ?? account.cash) || 0;
  let totalAsset = accountTotalAsset > 0 ? accountTotalAsset : accountCash + holdingsMarketValue;
  if (totalAsset < holdingsMarketValue) totalAsset = holdingsMarketValue + Math.max(accountCash, 0);
  const marketValue = holdings.length ? holdingsMarketValue : Number(account.market_value) || 0;
  const availableCash = totalAsset > 0 ? Math.max(totalAsset - marketValue, 0) : accountCash;
  const allocationBase = Math.max(totalAsset, marketValue + availableCash, 1);
  const marketPct = clamp((marketValue / allocationBase) * 100, 0, 100);
  const positionRatio = totalAsset > 0 ? marketValue / totalAsset : 0;
  const maxHoldingValue = holdings.reduce((max, item) => Math.max(max, holdingMarketValue(item)), 0);
  const singleStockRatio = totalAsset > 0 ? maxHoldingValue / totalAsset : 0;
  const maxPositionRatio = Number(risk.max_position_ratio);
  const maxSingleStockRatio = Number(risk.max_single_stock_ratio);
  const maxDailyTrades = Number(risk.max_daily_trades);
  const today = String(data.updated_at || "").slice(0, 10);
  const tradesToday = dailyTradeCount(data, today);
  const status = accountStatus(account, holdings);

  setTag("accountMode", status.label, status.className, status.title);
  text("totalAsset", formatMoney(totalAsset));
  text("availableCash", formatMoney(availableCash));
  text("marketValue", formatMoney(marketValue));
  text("positionCount", data.metrics?.holdings_count ?? holdings.length ?? account.position_count ?? 0);
  text("assetPositionRatio", formatPercent(positionRatio));
  text("assetMarketLegend", `${formatMoney(marketValue)} · ${marketPct.toFixed(1)}%`);
  text("assetCashLegend", `${formatMoney(availableCash)} · ${(100 - marketPct).toFixed(1)}%`);
  text("assetRiskLegend", risk.stop_trading ? "停止交易" : "正常");

  renderRiskPill("maxPositionRatio", {
    label: "总仓位",
    value: formatPercent(positionRatio),
    meta: Number.isFinite(maxPositionRatio) ? `上限 ${formatPercent(maxPositionRatio)}` : "未设上限",
    usage: Number.isFinite(maxPositionRatio) && maxPositionRatio > 0 ? positionRatio / maxPositionRatio : 0,
    detail: `当前持仓市值 ${formatMoney(marketValue)} / 总资产 ${formatMoney(totalAsset)}`,
  });
  renderRiskPill("maxSingleStockRatio", {
    label: "单票",
    value: formatPercent(singleStockRatio),
    meta: Number.isFinite(maxSingleStockRatio) ? `上限 ${formatPercent(maxSingleStockRatio)}` : "未设上限",
    usage: Number.isFinite(maxSingleStockRatio) && maxSingleStockRatio > 0 ? singleStockRatio / maxSingleStockRatio : 0,
    detail: `最大单票市值 ${formatMoney(maxHoldingValue)} / 总资产 ${formatMoney(totalAsset)}`,
  });
  renderRiskPill("maxDailyTrades", {
    label: "日交易",
    value: `${tradesToday}`,
    meta: Number.isFinite(maxDailyTrades) ? `上限 ${maxDailyTrades}` : "未设上限",
    usage: Number.isFinite(maxDailyTrades) && maxDailyTrades > 0 ? tradesToday / maxDailyTrades : 0,
    detail: `${today || "今日"} 已记录交易 ${tradesToday} 次`,
  });
  renderRiskPill("stopTrading", {
    label: "风控",
    value: risk.stop_trading ? "停止交易" : "正常",
    meta: risk.stop_trading ? "已触发硬停止" : "未触发硬停止",
    usage: risk.stop_trading ? 1 : 0,
    hardStop: Boolean(risk.stop_trading),
  });

  const assetPie = $("assetPie");
  if (assetPie) {
    assetPie.style.background = `conic-gradient(var(--accent) 0 ${marketPct}%, var(--surface-3) ${marketPct}% 100%)`;
  }
}

function renderMarket(data) {
  if (!$("marketRisk") && !$("marketSummary")) return;
  const market = data.market || {};
  const status = marketStatus(market);
  setTag("marketRisk", status.label, status.className, status.title);
  text("marketDate", market.date || "--");
  text("marketUpdatedAt", compactDateTime(market.updated_at));
  text("marketSummary", market.summary || "暂无市场摘要");

  renderMarketSentiment(market);
  renderMarketItems("marketHotTopics", "marketHotCount", market.hot_topics, "暂无热点");
  renderMarketItems("marketWatchSectors", "marketWatchCount", market.watch_sectors, "暂无关注方向");
  renderMarketItems("marketAvoidSectors", "marketAvoidCount", market.avoid_sectors, "暂无回避方向");
  renderMarketEvents("marketKeyEvents", "marketEventCount", market.key_events);
}

function renderMarketSentiment(market) {
  const sentiment = market.market_sentiment || market.sentiment || {};
  const rawScore = Number(sentiment.score ?? market.market_sentiment_score ?? market.sentiment_score);
  const score = Number.isFinite(rawScore) ? clamp(rawScore, 0, 100) : null;
  const labelKey = String(sentiment.label || market.sentiment_label || "unknown").toLowerCase();
  const label = marketSentimentLabels[labelKey] || sentiment.label || market.sentiment_label || "未知";
  const gauge = $("marketSentimentGauge");

  if (gauge) {
    gauge.classList.toggle("empty", score === null);
    const activeSegments = score === null ? 0 : Math.max(1, Math.ceil(score / 10));
    gauge.querySelectorAll(".sentiment-segments i").forEach((segment, index) => {
      segment.classList.toggle("active", index < activeSegments);
    });
  }
  text("marketSentimentScore", score === null ? "--" : `${Math.round(score)}`);
  text("marketSentimentLabel", label);
}

function renderMarketItems(containerId, countId, values, emptyText) {
  const node = $(containerId);
  const items = Array.isArray(values) ? values : [];
  text(countId, items.length);
  if (!node) return;
  clearNode(node);

  items.slice(0, 8).forEach((value) => {
    const item = document.createElement("span");
    item.className = "market-item";
    item.textContent = shortText(value);
    item.title = item.textContent;
    node.appendChild(item);
  });

  if (!node.childElementCount) {
    const item = document.createElement("span");
    item.className = "market-item muted-item";
    item.textContent = emptyText;
    node.appendChild(item);
  }
}

function eventTitle(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value.event || value.title || value.name || value.summary || JSON.stringify(value);
  }
  return shortText(value);
}

function eventMeta(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  return [value.date, value.impact || value.reason || value.note].filter(Boolean).join(" · ");
}

function renderMarketEvents(containerId, countId, values) {
  const node = $(containerId);
  const events = Array.isArray(values) ? values : [];
  text(countId, events.length);
  if (!node) return;
  clearNode(node);

  events.slice(0, 5).forEach((value) => {
    const item = document.createElement("div");
    item.className = "market-event";
    const title = document.createElement("strong");
    title.textContent = eventTitle(value);
    item.appendChild(title);

    const metaText = eventMeta(value);
    if (metaText) {
      const meta = document.createElement("span");
      meta.textContent = metaText;
      item.appendChild(meta);
    }

    node.appendChild(item);
  });

  if (!node.childElementCount) {
    const item = document.createElement("div");
    item.className = "market-event muted-item";
    item.textContent = "暂无关键事件";
    node.appendChild(item);
  }
}

function enabledText(value) {
  return value === false ? "停用" : "启用";
}

function timeToMinutes(time) {
  const match = String(time || "").match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function triggerBucket(job) {
  const name = String(job.name || "").toLowerCase();
  const reason = String(job.trigger_reason || "").toLowerCase();
  const minutes = timeToMinutes(job.time);

  if (name.includes("pre") || reason.includes("pre") || (minutes !== null && minutes < 570)) return "pre";
  if (name.includes("post") || name.includes("night") || name.includes("evening") || reason.includes("post") || reason.includes("review") || reason.includes("plan") || (minutes !== null && minutes >= 900)) return "post";
  return "mid";
}

function marketIntervalLabel(sessions) {
  const values = [...new Set(sessions.map((session) => Number(session.interval_minutes)).filter(Number.isFinite))];
  if (!values.length) return "--";
  return values.length === 1 ? `${values[0]} 分钟` : values.map((value) => `${value}m`).join(" / ");
}

function renderTriggerGroup(parent, config) {
  const group = document.createElement("section");
  group.className = `trigger-group ${config.kind || ""}`.trim();

  const head = document.createElement("div");
  head.className = "trigger-group-head";
  const titleWrap = document.createElement("div");
  const label = document.createElement("span");
  label.textContent = config.label;
  const title = document.createElement("strong");
  title.textContent = config.title;
  titleWrap.appendChild(label);
  titleWrap.appendChild(title);

  const count = document.createElement("em");
  count.textContent = config.count;
  head.appendChild(titleWrap);
  head.appendChild(count);
  group.appendChild(head);

  const rows = document.createElement("div");
  rows.className = "trigger-group-rows";
  if (config.times.length) {
    config.times.forEach((item) => renderTriggerTime(rows, item.label, item.enabled, item.title));
  } else {
    renderTriggerTime(rows, config.emptyTitle || "暂无配置", false);
  }
  group.appendChild(rows);
  parent.appendChild(group);
}

function renderTriggerTime(parent, label, enabled = true, title = "") {
  const chip = document.createElement("span");
  chip.className = `trigger-time ${enabled ? "" : "disabled"}`.trim();
  chip.textContent = label;
  chip.title = title || label;
  parent.appendChild(chip);
}

function jobTimeChips(jobs) {
  return jobs.map((job) => ({
    label: job.time || "--:--",
    title: `${job.name || "fixed_job"} · ${enabledText(job.enabled)} · ${job.trigger_reason || "--"}`,
    enabled: job.enabled !== false,
  }));
}

function sessionTimeChips(sessions) {
  return sessions.map((session) => ({
    label: `${session.start || "--:--"}-${session.end || "--:--"}`,
    title: `盘中巡检 · 每 ${session.interval_minutes || "--"} 分钟先调用子 Agent，再按需唤醒主 Agent`,
    enabled: true,
  }));
}

function renderSchedulerOverview(configPayload) {
  const payload = configPayload || {};
  const config = payload.config || {};
  const fixedJobs = Array.isArray(config.fixed_jobs) ? config.fixed_jobs : [];
  const sessions = Array.isArray(config.market_sessions) ? config.market_sessions : [];
  const subagents = Array.isArray(config.market_subagents) ? config.market_subagents : [];
  const preJobs = fixedJobs.filter((job) => triggerBucket(job) === "pre");
  const midJobs = fixedJobs.filter((job) => triggerBucket(job) === "mid");
  const postJobs = fixedJobs.filter((job) => triggerBucket(job) === "post");
  const activeSubagents = subagents.filter((item) => item.enabled !== false);
  const marketSubagents = subagents.filter((item) => !item.time);
  const activeMarketSubagents = marketSubagents.filter((item) => item.enabled !== false);

  text("schedulerIntervalSummary", marketIntervalLabel(sessions));
  text("schedulerFixedSummary", `${preJobs.filter((job) => job.enabled !== false).length} 次`);
  text("schedulerSessionSummary", `${midJobs.filter((job) => job.enabled !== false).length} 次`);
  text("schedulerSubagentSummary", `${activeSubagents.length}/${subagents.length}`);

  const list = $("schedulerTriggerList");
  if (!list) return;
  clearNode(list);

  renderTriggerGroup(list, {
    kind: "pre",
    label: "PRE",
    title: "盘前唤醒",
    count: `${preJobs.filter((job) => job.enabled !== false).length}/${preJobs.length}`,
    times: jobTimeChips(preJobs),
    emptyTitle: "暂无盘前任务",
  });

  renderTriggerGroup(list, {
    kind: "post",
    label: "POST",
    title: "盘后唤醒",
    count: `${postJobs.filter((job) => job.enabled !== false).length}/${postJobs.length}`,
    times: jobTimeChips(postJobs),
    emptyTitle: "暂无盘后任务",
  });

  renderTriggerGroup(list, {
    kind: "mid",
    label: "LIVE",
    title: "盘中巡检",
    count: `${sessions.length} 段 · ${activeMarketSubagents.length}/${marketSubagents.length} agent`,
    times: sessionTimeChips(sessions),
    emptyTitle: "暂无盘中巡检",
  });

  renderTriggerGroup(list, {
    kind: "wake",
    label: "WAKE",
    title: "盘中唤醒",
    count: `${midJobs.filter((job) => job.enabled !== false).length}/${midJobs.length}`,
    times: jobTimeChips(midJobs),
    emptyTitle: "暂无盘中唤醒",
  });
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
  const currentHoldings = activeHoldings(holdings || []);
  const marketTotal = currentHoldings.reduce((sum, item) => sum + holdingMarketValue(item), 0);
  const pnlTotal = currentHoldings.reduce((sum, item) => sum + (Number(item.unrealized_pnl) || 0), 0);
  const largest = currentHoldings.reduce((best, item) => {
    const value = holdingMarketValue(item);
    return value > (best ? holdingMarketValue(best) : 0) ? item : best;
  }, null);

  text("holdingsMarketTotal", formatMoney(marketTotal));
  text("holdingsPnlTotal", formatMoney(pnlTotal));
  text("largestHolding", largest ? `${largest.name || largest.symbol} · ${formatMoney(holdingMarketValue(largest))}` : "--");
  text("holdingsPieText", currentHoldings.length ? `${currentHoldings.length} 只` : "空");

  const pnlNode = $("holdingsPnlTotal");
  if (pnlNode) {
    pnlNode.classList.toggle("positive", pnlTotal >= 0);
    pnlNode.classList.toggle("negative", pnlTotal < 0);
  }

  const pie = $("holdingsPie");
  const legend = $("holdingsLegend");
  if (!pie || !legend) return;

  clearNode(legend);

  if (!currentHoldings.length || marketTotal <= 0) {
    pie.style.background = "conic-gradient(var(--surface-3) 0 100%)";
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = "暂无持仓分布";
    legend.appendChild(empty);
    return;
  }

  let cursor = 0;
  const segments = currentHoldings.map((item, index) => {
    const value = holdingMarketValue(item);
    const percent = marketTotal > 0 ? (value / marketTotal) * 100 : 0;
    const start = cursor;
    const end = cursor + percent;
    cursor = end;
    return `${holdingColor(index)} ${start}% ${end}%`;
  });
  pie.style.background = `conic-gradient(${segments.join(", ")})`;

  currentHoldings.slice(0, 6).forEach((item, index) => {
    const value = holdingMarketValue(item);
    const row = document.createElement("div");
    const dot = document.createElement("span");
    dot.className = "legend-dot";
    dot.style.background = holdingColor(index);

    const name = document.createElement("span");
    name.className = "holding-legend-name";
    name.textContent = shortText(item.name || item.symbol);
    name.title = name.textContent;

    const percent = document.createElement("strong");
    percent.textContent = formatPercent(value / marketTotal);

    row.appendChild(dot);
    row.appendChild(name);
    row.appendChild(percent);
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

function schedulerInput(type, field, value, placeholder = "") {
  const input = document.createElement("input");
  input.type = type;
  input.dataset.field = field;
  input.placeholder = placeholder;
  if (type === "checkbox") {
    input.checked = value !== false;
  } else {
    input.value = value ?? "";
  }
  if (type === "number") {
    input.min = field === "interval_minutes" ? "1" : "5";
    input.max = field === "interval_minutes" ? "240" : "3600";
    input.step = "1";
  }
  return input;
}

function schedulerCell(label, input) {
  const wrap = document.createElement("label");
  wrap.className = "scheduler-cell";
  const span = document.createElement("span");
  span.textContent = label;
  wrap.appendChild(span);
  wrap.appendChild(input);
  return wrap;
}

function createSchedulerRow(kind, item = {}) {
  const row = document.createElement("div");
  row.className = `scheduler-config-row ${kind}`;
  row.dataset.kind = kind;

  if (kind === "fixed") {
    row.appendChild(schedulerCell("启用", schedulerInput("checkbox", "enabled", item.enabled)));
    row.appendChild(schedulerCell("名称", schedulerInput("text", "name", item.name || "", "premarket_0830")));
    row.appendChild(schedulerCell("时间", schedulerInput("time", "time", item.time || "09:30")));
    row.appendChild(schedulerCell("触发原因", schedulerInput("text", "trigger_reason", item.trigger_reason || "", "scheduled_premarket")));
    row.appendChild(schedulerCell("命令", schedulerInput("text", "command", item.command || "", "留空使用主 Agent 命令")));
  }

  if (kind === "session") {
    row.appendChild(schedulerCell("开始", schedulerInput("time", "start", item.start || "09:30")));
    row.appendChild(schedulerCell("结束", schedulerInput("time", "end", item.end || "11:30")));
    row.appendChild(schedulerCell("间隔分钟", schedulerInput("number", "interval_minutes", item.interval_minutes || 10)));
  }

  if (kind === "subagent") {
    row.appendChild(schedulerCell("启用", schedulerInput("checkbox", "enabled", item.enabled)));
    const nameInput = schedulerInput("text", "name", item.name || "", "holding_follow");
    nameInput.readOnly = true;
    row.appendChild(schedulerCell("名称", nameInput));
    row.appendChild(schedulerCell("触发时间", schedulerInput("time", "time", item.time || "")));
    row.appendChild(schedulerCell("命令", schedulerInput("text", "command", item.command || "", "python -m subagent.holding_follow.exec_agent")));
  }

  if (kind !== "subagent") {
    const remove = document.createElement("button");
    remove.className = "icon-button scheduler-remove";
    remove.type = "button";
    remove.title = "删除";
    remove.dataset.action = "remove-scheduler-row";
    remove.textContent = "×";
    row.appendChild(remove);
  }
  return row;
}

function renderSchedulerRows(containerId, kind, rows) {
  const container = $(containerId);
  if (!container) return;
  clearNode(container);

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "scheduler-empty";
    empty.textContent = "暂无配置";
    container.appendChild(empty);
    return;
  }

  rows.forEach((item) => container.appendChild(createSchedulerRow(kind, item)));
}

function renderSchedulerConfig(configPayload, force = false) {
  const panel = $("schedulerTimezone");
  if (!panel || !configPayload || (state.schedulerConfigRendered && !force)) return;

  const config = configPayload.config || {};
  text("schedulerConfigFile", configPayload.file || "config/scheduler.json");
  $("schedulerTimezone").value = config.timezone || "Asia/Shanghai";
  $("schedulerMainCommand").value = config.main_agent_command || "python -m runtime.launcher";
  $("schedulerCheckInterval").value = config.check_interval_seconds || 30;
  $("schedulerWeekdaysOnly").checked = config.run_on_weekdays_only !== false;

  renderSchedulerRows("fixedJobsEditor", "fixed", Array.isArray(config.fixed_jobs) ? config.fixed_jobs : []);
  renderSchedulerRows("marketSessionsEditor", "session", Array.isArray(config.market_sessions) ? config.market_sessions : []);
  renderSchedulerRows("marketSubagentsEditor", "subagent", Array.isArray(config.market_subagents) ? config.market_subagents : []);

  state.schedulerConfigRendered = true;
}

function collectSchedulerRows(containerId) {
  return [...document.querySelectorAll(`#${containerId} .scheduler-config-row`)].map((row) => {
    const item = {};
    row.querySelectorAll("[data-field]").forEach((input) => {
      const field = input.dataset.field;
      if (input.type === "checkbox") {
        item[field] = input.checked;
      } else if (input.type === "number") {
        item[field] = Number(input.value);
      } else {
        item[field] = input.value.trim();
      }
    });
    return item;
  });
}

function collectSchedulerConfig() {
  return {
    timezone: $("schedulerTimezone").value.trim() || "Asia/Shanghai",
    main_agent_command: $("schedulerMainCommand").value.trim(),
    check_interval_seconds: Number($("schedulerCheckInterval").value),
    run_on_weekdays_only: $("schedulerWeekdaysOnly").checked,
    fixed_jobs: collectSchedulerRows("fixedJobsEditor"),
    market_sessions: collectSchedulerRows("marketSessionsEditor"),
    market_subagents: collectSchedulerRows("marketSubagentsEditor"),
  };
}

function validateTimeInput(value, label) {
  if (!/^\d{2}:\d{2}$/.test(String(value || ""))) return `${label} 必须是 HH:MM`;
  return "";
}

function validateSchedulerConfig(config) {
  if (!config.main_agent_command) return "主 Agent 命令不能为空";
  if (!Number.isInteger(config.check_interval_seconds) || config.check_interval_seconds < 5 || config.check_interval_seconds > 3600) {
    return "检查间隔必须在 5 到 3600 秒之间";
  }

  for (const [index, job] of config.fixed_jobs.entries()) {
    if (!job.name) return `固定任务 #${index + 1} 名称不能为空`;
    const timeError = validateTimeInput(job.time, `固定任务 #${index + 1} 时间`);
    if (timeError) return timeError;
    if (!job.trigger_reason) return `固定任务 #${index + 1} 触发原因不能为空`;
  }

  for (const [index, session] of config.market_sessions.entries()) {
    const startError = validateTimeInput(session.start, `交易时段 #${index + 1} 开始时间`);
    if (startError) return startError;
    const endError = validateTimeInput(session.end, `交易时段 #${index + 1} 结束时间`);
    if (endError) return endError;
    if (!Number.isInteger(session.interval_minutes) || session.interval_minutes < 1 || session.interval_minutes > 240) {
      return `交易时段 #${index + 1} 间隔必须在 1 到 240 分钟之间`;
    }
  }

  for (const [index, subagent] of config.market_subagents.entries()) {
    if (!subagent.name) return `子 Agent #${index + 1} 名称不能为空`;
    if (subagent.time) {
      const timeError = validateTimeInput(subagent.time, `子 Agent #${index + 1} 触发时间`);
      if (timeError) return timeError;
    }
    if (!subagent.command) return `子 Agent #${index + 1} 命令不能为空`;
  }

  return "";
}

async function saveSchedulerConfig() {
  const button = $("saveSchedulerConfigBtn");
  button.disabled = true;
  setMessage("schedulerConfigMessage", "保存中...");

  try {
    const config = collectSchedulerConfig();
    const validationError = validateSchedulerConfig(config);
    if (validationError) throw new Error(validationError);

    const response = await fetch("/api/scheduler-config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || "保存失败");

    state.schedulerConfigRendered = false;
    renderSchedulerConfig(data.config, true);
    renderSchedulerOverview(data.config);
    setMessage("schedulerConfigMessage", data.message || "已保存 Scheduler 配置", "ok");
    await refresh();
  } catch (error) {
    setMessage("schedulerConfigMessage", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function addSchedulerRow(containerId, kind, item) {
  const container = $(containerId);
  if (!container) return;
  const empty = container.querySelector(".scheduler-empty");
  if (empty) empty.remove();
  container.appendChild(createSchedulerRow(kind, item));
}

function addFixedJob() {
  addSchedulerRow("fixedJobsEditor", "fixed", {
    name: `custom_${Date.now().toString().slice(-4)}`,
    enabled: true,
    time: "09:30",
    trigger_reason: "scheduled_custom",
  });
}

function addMarketSession() {
  addSchedulerRow("marketSessionsEditor", "session", {
    start: "09:30",
    end: "11:30",
    interval_minutes: 10,
  });
}

function handleSchedulerEditorClick(event) {
  const button = event.target.closest("[data-action='remove-scheduler-row']");
  if (!button) return;
  const row = button.closest(".scheduler-config-row");
  const list = row?.parentElement;
  row?.remove();
  if (list && !list.querySelector(".scheduler-config-row")) {
    const empty = document.createElement("div");
    empty.className = "scheduler-empty";
    empty.textContent = "暂无配置";
    list.appendChild(empty);
  }
}

function latestInitializationDate(data) {
  const initialization = data.initialization || {};
  const values = [];

  if (initialization.active) {
    values.push(initialization.active.started_at);
  }

  (initialization.recent || []).forEach((run) => {
    values.push(run.ended_at || run.started_at);
  });

  return latestDateTime(values);
}

function manualRunDate(run) {
  return parseDateTime(run?.ended_at || run?.started_at || "");
}

function visibleManualRunState(data) {
  const manual = data.manual_run || {};
  const cutoff = latestInitializationDate(data);
  if (!cutoff) return manual;

  return {
    ...manual,
    recent: (manual.recent || []).filter((run) => {
      const runDate = manualRunDate(run);
      return runDate && runDate > cutoff;
    }),
  };
}

function renderManual(data) {
  const manual = visibleManualRunState(data);
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

function alarmStatusClass(status) {
  if (status === "soon") return "soon";
  if (status === "scheduled") return "scheduled";
  if (status === "expired" || status === "invalid") return "expired";
  if (status === "done") return "done";
  return "disabled";
}

function renderAlarm(alarm) {
  const source = $("alarmSource");
  const globalStatus = $("alarmGlobalStatus");
  const nextTime = $("nextAlarmTime");
  const list = $("alarmList");
  if (!list) return;

  clearNode(list);

  if (!alarm) {
    if (source) source.textContent = "config/alarm.json";
    if (globalStatus) globalStatus.textContent = "服务未更新";
    if (nextTime) nextTime.textContent = "--";

    const item = document.createElement("div");
    item.className = "alarm-empty error";
    item.textContent = "当前 dashboard 服务未返回 Alarm 数据，请重启 dashboard 后刷新。";
    list.appendChild(item);
    return;
  }

  const items = Array.isArray(alarm.items) ? alarm.items : [];
  const next = alarm.next_alarm || null;

  if (source) source.textContent = alarm.file || "config/alarm.json";
  if (globalStatus) {
    globalStatus.textContent = alarm.enabled === false
      ? "全局停用"
      : `${alarm.active_count || 0}/${alarm.total || 0} 启用`;
  }
  if (nextTime) {
    nextTime.textContent = next?.next_at ? compactDateTime(next.next_at) : "暂无";
  }

  if (alarm?.error) {
    const item = document.createElement("div");
    item.className = "alarm-empty error";
    item.textContent = alarm.error;
    list.appendChild(item);
    return;
  }

  if (!items.length) {
    const item = document.createElement("div");
    item.className = "alarm-empty";
    item.textContent = "暂无 Alarm 配置";
    list.appendChild(item);
    return;
  }

  items.slice(0, 5).forEach((alarmItem) => {
    const item = document.createElement("div");
    item.className = `alarm-item ${alarmStatusClass(alarmItem.status)}`;
    item.title = alarmItem.task || "";

    const time = document.createElement("span");
    time.textContent = alarmItem.next_at ? compactDateTime(alarmItem.next_at) : alarmItem.schedule || "--";

    const body = document.createElement("div");
    const head = document.createElement("strong");
    head.textContent = alarmItem.name || alarmItem.alarm_id || "Alarm";

    const meta = document.createElement("small");
    meta.textContent = `${alarmItem.status_label || "--"} · ${alarmItem.schedule || "--"}`;

    body.appendChild(head);
    body.appendChild(meta);
    item.appendChild(time);
    item.appendChild(body);
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
        : "清空运行数据、Alarm 和页面历史"
  );

  renderAlarm(data.alarm);

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
  const ok = window.confirm("初始化会清空 pools/logs/memory/reports、Alarm 和页面历史，并重置账户和市场状态。确定继续？");
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

function workstreamStatusClass(status) {
  if (status === "final") return "success";
  if (status === "tool_call") return "running";
  if (status === "thinking" || status === "preparing") return "";
  return "";
}

function workflowModeLabel(mode) {
  const normalized = String(mode || "").toLowerCase();
  if (normalized === "manual") return "人工模式";
  if (normalized === "scheduler") return "定时调度";
  if (normalized === "trigger") return "触发模式";
  return "主 Agent";
}

function workflowRunMeta(run) {
  const runId = String(run?.run_id || "");
  const matched = runId.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_([a-zA-Z_]+)$/);
  if (matched) {
    return {
      time: `${matched[1]}年${matched[2]}月${matched[3]}日，${matched[4]}:${matched[5]}`,
      mode: workflowModeLabel(matched[7]),
    };
  }

  return {
    time: run?.timestamp ? compactDateTime(run.timestamp) : "等待工作流",
    mode: workflowModeLabel(run?.mode),
  };
}

function traceToWorkstream(trace, fallbackRun) {
  const steps = Array.isArray(trace.steps) ? trace.steps : [];
  const entries = steps
    .filter((step) => step.kind !== "tool" && ["thinking", "tool_call", "final"].includes(step.type))
    .map((step) => {
      if (step.type === "thinking") {
        return {
          step: step.step,
          timestamp: step.timestamp,
          type: "thinking",
          label: "思考",
          text: step.next_action || step.body || "",
        };
      }
      if (step.type === "tool_call") {
        return {
          step: step.step,
          timestamp: step.timestamp,
          type: "tool_call",
          label: "执行工具",
          tool: step.tool || "",
          text: step.reason || step.body || "",
        };
      }
      return {
        step: step.step,
        timestamp: step.timestamp,
        type: "final",
        label: "完成",
        text: step.summary || step.body || "",
      };
    })
    .filter((entry) => entry.text);

  const last = entries[entries.length - 1] || {};
  const lastStep = steps[steps.length - 1] || {};
  const active = !entries.some((entry) => entry.type === "final");
  const status = active ? (lastStep.kind === "tool" ? "thinking" : (last.type || "preparing")) : "final";
  const run = trace.run || fallbackRun || {};

  return {
    status,
    status_label: status === "tool_call" ? "执行工具" : status === "thinking" ? "思考中" : active ? "准备中" : "已完成",
    active,
    run,
    entries: entries.slice(-10),
  };
}

function renderAgentWorkstreamStream(stream) {
  const list = $("agentWorkstreamList");
  const badge = $("agentWorkstreamStatus");
  const metaNode = $("agentWorkstreamMeta");
  if (!list) return;

  if (badge) {
    badge.textContent = stream.status_label || "待命";
    badge.className = `tag ${workstreamStatusClass(stream.status)}`.trim();
  }

  clearNode(list);

  const run = stream.run || {};
  const entries = Array.isArray(stream.entries) ? stream.entries : [];
  const workflowMeta = workflowRunMeta(run);
  if (metaNode) {
    metaNode.textContent = run.run_id || entries.length ? `${workflowMeta.time} · ${workflowMeta.mode}` : "等待工作流";
  }
  const orderedEntries = entries.slice().reverse();

  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "workstream-empty";
    const title = document.createElement("strong");
    title.textContent = "暂无工作轨迹";
    const body = document.createElement("p");
    body.textContent = "主 Agent 开始运行后，这里会实时显示 next_action、tool_call reason 和最终 summary。";
    empty.appendChild(title);
    empty.appendChild(body);
    list.appendChild(empty);
    return;
  }

  orderedEntries.forEach((entry, index) => {
    const item = document.createElement("div");
    item.className = `workstream-item ${entry.type || ""}${index === 0 ? " current" : ""}`.trim();

    const rail = document.createElement("span");
    rail.className = "workstream-dot";

    const content = document.createElement("div");
    content.className = "workstream-content";

    const head = document.createElement("div");
    head.className = "workstream-head";

    const label = document.createElement("strong");
    label.textContent = entry.label || "--";

    const meta = document.createElement("span");
    const parts = [];
    if (entry.step) parts.push(`Step ${entry.step}`);
    if (entry.tool) parts.push(entry.tool);
    if (entry.timestamp) parts.push(compactDateTime(entry.timestamp));
    meta.textContent = parts.join(" · ");

    const body = document.createElement("p");
    body.textContent = entry.text || "暂无内容";

    head.appendChild(label);
    head.appendChild(meta);
    content.appendChild(head);
    content.appendChild(body);
    item.appendChild(rail);
    item.appendChild(content);
    list.appendChild(item);
  });
}

async function loadWorkstreamFallback(data) {
  if (state.workstreamFallbackLoading) return;
  const run = data.logs?.run_dirs?.[0];
  if (!run?.run_id) return;

  state.workstreamFallbackLoading = true;
  state.workstreamFallbackRunId = run.run_id;

  try {
    const response = await fetch(`/api/trace?run_id=${encodeURIComponent(run.run_id)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const trace = await response.json();
    if (state.workstreamFallbackRunId === run.run_id) {
      renderAgentWorkstreamStream(traceToWorkstream(trace, run));
    }
  } catch (error) {
    console.error(error);
  } finally {
    state.workstreamFallbackLoading = false;
  }
}

function renderAgentWorkstream(data) {
  const stream = data.agent_workstream || null;
  if (stream && (stream.run || (Array.isArray(stream.entries) && stream.entries.length))) {
    renderAgentWorkstreamStream(stream);
    return;
  }

  renderAgentWorkstreamStream({
    status: "preparing",
    status_label: "同步中",
    active: false,
    run: data.logs?.run_dirs?.[0] || null,
    entries: [],
  });
  loadWorkstreamFallback(data);
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
  renderAgentWorkstream(state.snapshot || {});
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
  renderSchedulerOverview(data.scheduler_config);
  renderSchedulerConfig(data.scheduler_config);
  renderManual(data);
  renderSystem(data);
  if (state.selectedRunId) {
    const stillExists = (data.logs?.run_dirs || []).some((run) => run.run_id === state.selectedRunId);
    if (!stillExists) {
      state.selectedRunId = data.logs?.run_dirs?.[0]?.run_id || "";
    }
  }
  renderAgentWorkstream(data);
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
    setMessage("schedulerConfigMessage", "保存调度配置需要 dashboard 服务在线。", "error");
    console.error(error);
  } finally {
    state.refreshing = false;
  }
}

function bindEvents() {
  $("refreshBtn").addEventListener("click", () => refresh());
  $("saveStyleBtn").addEventListener("click", () => saveStyle());
  $("saveApiBtn").addEventListener("click", () => saveApiConfig());
  $("saveSchedulerConfigBtn").addEventListener("click", () => saveSchedulerConfig());
  $("addFixedJobBtn").addEventListener("click", () => addFixedJob());
  $("addMarketSessionBtn").addEventListener("click", () => addMarketSession());
  $("fixedJobsEditor").addEventListener("click", handleSchedulerEditorClick);
  $("marketSessionsEditor").addEventListener("click", handleSchedulerEditorClick);
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
