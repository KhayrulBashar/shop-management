/**
 * Shop Management System - AI Assistant Client Module
 * Supports conversational text, Web Speech voice recognition (Bengali & English),
 * interactive mutation confirmation cards, and live dashboard auto-refresh.
 */

(function () {
  "use strict";

  // Persistent session identifier
  window.aiSessionId = localStorage.getItem("shopmanage_ai_session_id") || null;
  let recognition = null;
  let isListening = false;

  document.addEventListener("DOMContentLoaded", () => {
    initAssistantUI();
    initSpeechRecognition();
  });

  // ---------------------------------------------------------------------------
  // 1. UI Initialization & Drawer Controls
  // ---------------------------------------------------------------------------
  function initAssistantUI() {
    const openBtn = document.getElementById("aiOpenDrawerBtn");
    const closeBtn = document.getElementById("aiCloseDrawerBtn");
    const backdrop = document.getElementById("aiDrawerBackdrop");
    const clearBtn = document.getElementById("aiClearHistoryBtn");
    const form = document.getElementById("aiChatForm");
    const textInput = document.getElementById("aiTextInput");

    if (openBtn) {
      openBtn.addEventListener("click", openDrawer);
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", closeDrawer);
    }
    if (backdrop) {
      backdrop.addEventListener("click", closeDrawer);
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", handleClearHistory);
    }

    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const msg = textInput ? textInput.value.trim() : "";
        if (msg) {
          submitAiMessage(msg);
          textInput.value = "";
        }
      });
    }

    // Escape key closes drawer
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        const drawer = document.getElementById("aiAssistantDrawer");
        if (drawer && !drawer.classList.contains("translate-x-full")) {
          closeDrawer();
        }
      }
    });
  }

  function openDrawer() {
    const drawer = document.getElementById("aiAssistantDrawer");
    const backdrop = document.getElementById("aiDrawerBackdrop");
    if (drawer) drawer.classList.remove("translate-x-full");
    if (backdrop) backdrop.classList.remove("hidden");
    const textInput = document.getElementById("aiTextInput");
    if (textInput) {
      setTimeout(() => textInput.focus(), 250);
    }
    if (window.lucide) window.lucide.createIcons();
  }

  function closeDrawer() {
    const drawer = document.getElementById("aiAssistantDrawer");
    const backdrop = document.getElementById("aiDrawerBackdrop");
    if (drawer) drawer.classList.add("translate-x-full");
    if (backdrop) backdrop.classList.add("hidden");
    if (isListening) stopListening();
  }

  // Quick Prompt Chip Handler
  window.aiQuickPrompt = function (text) {
    const input = document.getElementById("aiTextInput");
    if (input) input.value = text;
    submitAiMessage(text);
    if (input) input.value = "";
  };

  // ---------------------------------------------------------------------------
  // 2. Web Speech Recognition (Voice in Bengali / English)
  // ---------------------------------------------------------------------------
  function initSpeechRecognition() {
    const voiceBtn = document.getElementById("aiVoiceToggleBtn");
    const stopBtn = document.getElementById("aiStopVoiceBtn");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      if (voiceBtn) {
        voiceBtn.title = "Voice recognition not supported in this browser. Use Chrome, Edge, or Opera.";
        voiceBtn.classList.add("opacity-50", "cursor-not-allowed");
        voiceBtn.addEventListener("click", () => {
          if (window.showToast) {
            window.showToast("Voice recognition requires Google Chrome or modern Chromium browser.", "warning");
          }
        });
      }
      return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    // Default to Bengali; browser speech engines automatically transcribe English words spoken alongside Bengali
    recognition.lang = "bn-BD";

    recognition.onstart = () => {
      isListening = true;
      updateVoiceUI(true);
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript.trim();
      if (transcript) {
        const textInput = document.getElementById("aiTextInput");
        if (textInput) textInput.value = transcript;
        submitAiMessage(transcript);
        if (textInput) textInput.value = "";
      }
    };

    recognition.onerror = (event) => {
      console.warn("Speech recognition error:", event.error);
      stopListening();
      if (event.error !== "no-speech" && window.showToast) {
        window.showToast(`Voice input: ${event.error}`, "warning");
      }
    };

    recognition.onend = () => {
      isListening = false;
      updateVoiceUI(false);
    };

    if (voiceBtn) {
      voiceBtn.addEventListener("click", () => {
        if (isListening) {
          stopListening();
        } else {
          startListening();
        }
      });
    }

    if (stopBtn) {
      stopBtn.addEventListener("click", stopListening);
    }
  }

  function startListening() {
    if (!recognition) return;
    try {
      recognition.start();
    } catch (e) {
      console.warn("Speech recognition start failed:", e);
    }
  }

  function stopListening() {
    if (!recognition) return;
    try {
      recognition.stop();
    } catch (e) {}
    isListening = false;
    updateVoiceUI(false);
  }

  function updateVoiceUI(active) {
    const voiceBtn = document.getElementById("aiVoiceToggleBtn");
    const banner = document.getElementById("aiVoiceListeningBanner");

    if (voiceBtn) {
      if (active) {
        voiceBtn.classList.add("bg-rose-600", "text-white", "animate-pulse", "border-rose-500");
        voiceBtn.classList.remove("text-slate-300", "bg-brand-card");
      } else {
        voiceBtn.classList.remove("bg-rose-600", "text-white", "animate-pulse", "border-rose-500");
        voiceBtn.classList.add("text-slate-300", "bg-brand-card");
      }
    }

    if (banner) {
      if (active) {
        banner.classList.remove("hidden");
      } else {
        banner.classList.add("hidden");
      }
    }
  }

  // ---------------------------------------------------------------------------
  // 3. Chat Messaging & Server Communication
  // ---------------------------------------------------------------------------
  async function submitAiMessage(messageText) {
    const chatLog = document.getElementById("aiChatLog");
    const sendBtn = document.getElementById("aiSendBtn");
    if (!chatLog) return;

    // 1. Render User Message Bubble
    appendUserBubble(chatLog, messageText);
    scrollChatBottom();

    // 2. Render Loading Indicator
    const loadingId = "aiLoading_" + Date.now();
    appendLoadingBubble(chatLog, loadingId);
    scrollChatBottom();

    if (sendBtn) sendBtn.disabled = true;

    try {
      const res = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          message: messageText,
          session_id: window.aiSessionId,
        }),
      });

      // Remove loading indicator
      const loadingEl = document.getElementById(loadingId);
      if (loadingEl) loadingEl.remove();

      if (res.status === 401) {
        appendAssistantBubble(chatLog, "Session expired. Please log in again.", "danger");
        if (window.showToast) window.showToast("Session expired. Please log in.", "danger");
        return;
      }

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const errDetail = errData.detail || "Server error occurred. Please try again.";
        appendAssistantBubble(chatLog, `Error: ${errDetail}`, "danger");
        return;
      }

      const data = await res.json();

      // Persist session ID
      if (data.session_id) {
        window.aiSessionId = data.session_id;
        localStorage.setItem("shopmanage_ai_session_id", data.session_id);
      }

      // Render assistant textual answer
      appendAssistantBubble(chatLog, data.response);

      // Render custom data cards if read-only data was returned
      if (data.data) {
        renderDataPayloadCard(chatLog, data.data);
      }

      // Render interactive Pending Action Preview Card if mutation requires confirmation
      if (data.action_required && data.pending_action) {
        renderConfirmationCard(chatLog, data.pending_action);
      }

      // Render interactive Quick Reply Chips if present
      if (Array.isArray(data.quick_replies) && data.quick_replies.length > 0) {
        renderQuickReplies(chatLog, data.quick_replies);
      }

      scrollChatBottom();
    } catch (e) {
      console.error("AI Request failed:", e);
      const loadingEl = document.getElementById(loadingId);
      if (loadingEl) loadingEl.remove();
      appendAssistantBubble(chatLog, "Network connection error. Please check your internet and server connection.", "danger");
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      if (window.lucide) window.lucide.createIcons();
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Interactive Confirmation Card Handler (Confirm & Cancel)
  // ---------------------------------------------------------------------------
  function renderConfirmationCard(container, action) {
    const card = document.createElement("div");
    card.className = "bg-brand-card border-2 border-amber-500/60 rounded-2xl p-4 shadow-xl text-slate-200 mt-2 space-y-3";
    card.id = `actionCard_${action.action_token}`;

    let detailsListHtml = "";
    if (action.details && typeof action.details === "object") {
      detailsListHtml = '<div class="bg-brand-cardSub/80 rounded-xl p-3 border border-brand-border text-xs space-y-1">';
      for (const [key, val] of Object.entries(action.details)) {
        const displayVal = typeof val === "object" ? JSON.stringify(val) : val;
        detailsListHtml += `<div class="flex justify-between py-0.5 border-b border-brand-border/40 last:border-b-0"><span class="text-slate-400 font-medium">${key}:</span> <span class="font-bold text-slate-100">${displayVal}</span></div>`;
      }
      detailsListHtml += "</div>";
    }

    card.innerHTML = `
      <div class="flex items-center gap-2.5 text-amber-400 font-bold text-sm">
        <i data-lucide="alert-circle" class="w-5 h-5 flex-shrink-0"></i>
        <span>${action.title || "Confirmation Required"}</span>
      </div>
      <p class="text-xs text-slate-300 leading-relaxed">${action.summary || "Please confirm this operation."}</p>
      ${detailsListHtml}
      <div class="flex items-center gap-2 pt-1">
        <button onclick="window.confirmAiAction('${action.action_token}', this)" class="flex-1 py-2 px-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md shadow-emerald-900/30 flex items-center justify-center gap-1.5 transition-all">
          <i data-lucide="check" class="w-3.5 h-3.5"></i>
          <span>Confirm &amp; Execute</span>
        </button>
        <button onclick="window.editAiAction('${action.action_token}', this)" class="py-2 px-3 rounded-xl bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 hover:text-white font-medium text-xs border border-indigo-500/40 transition-all flex items-center gap-1">
          <i data-lucide="edit-3" class="w-3.5 h-3.5"></i>
          <span>Edit Details</span>
        </button>
        <button onclick="window.cancelAiAction('${action.action_token}', this)" class="py-2 px-3 rounded-xl bg-brand-cardSub hover:bg-brand-border text-slate-300 hover:text-white font-medium text-xs border border-brand-border transition-all">
          Cancel
        </button>
      </div>
    `;

    container.appendChild(card);
    if (window.lucide) window.lucide.createIcons({ root: card });
  }

  window.editAiAction = function (actionToken, btnElement) {
    submitAiMessage("Edit Details");
  };

  function renderQuickReplies(container, replies) {
    if (!Array.isArray(replies) || replies.length === 0) return;
    const chipsWrapper = document.createElement("div");
    chipsWrapper.className = "flex flex-wrap gap-1.5 mt-2 pt-0.5";
    replies.forEach((rep) => {
      const btn = document.createElement("button");
      btn.className = "px-3 py-1 rounded-full bg-brand-cardSub/90 hover:bg-brand-cyan/20 border border-brand-cyan/40 text-brand-cyan hover:text-white font-medium text-xs shadow-sm transition-all flex items-center gap-1 active:scale-95";
      btn.textContent = rep;
      btn.onclick = () => {
        submitAiMessage(rep);
      };
      chipsWrapper.appendChild(btn);
    });
    container.appendChild(chipsWrapper);
  }

  window.confirmAiAction = async function (actionToken, btnElement) {
    if (btnElement) {
      btnElement.disabled = true;
      btnElement.innerHTML = `<span class="animate-spin text-xs">⏳</span> Executing...`;
    }

    try {
      const res = await fetch("/api/ai/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ action_token: actionToken }),
      });

      const data = await res.json();
      const card = document.getElementById(`actionCard_${actionToken}`);

      if (res.ok && data.success) {
        if (card) {
          card.className = "bg-emerald-950/40 border-2 border-emerald-500/60 rounded-2xl p-4 text-emerald-200 mt-2 space-y-2";
          card.innerHTML = `
            <div class="flex items-center gap-2 font-bold text-sm text-emerald-300">
              <i data-lucide="check-circle-2" class="w-5 h-5 flex-shrink-0"></i>
              <span>Operation Completed</span>
            </div>
            <p class="text-xs text-slate-200">${data.message || "Executed successfully."}</p>
          `;
          if (window.lucide) window.lucide.createIcons({ root: card });
        }
        if (window.showToast) window.showToast(data.message || "Operation succeeded!", "success");

        // Trigger dynamic refresh on main application if present
        refreshMainAppViews();
      } else {
        const errorMsg = data.detail || data.message || "Failed to execute action.";
        if (card) {
          card.className = "bg-rose-950/40 border-2 border-rose-500/60 rounded-2xl p-4 text-rose-200 mt-2 space-y-2";
          card.innerHTML = `
            <div class="flex items-center gap-2 font-bold text-sm text-rose-300">
              <i data-lucide="x-circle" class="w-5 h-5 flex-shrink-0"></i>
              <span>Execution Failed</span>
            </div>
            <p class="text-xs text-slate-200">${errorMsg}</p>
          `;
          if (window.lucide) window.lucide.createIcons({ root: card });
        }
        if (window.showToast) window.showToast(errorMsg, "danger");
      }
    } catch (e) {
      console.error("Action confirmation error:", e);
      if (window.showToast) window.showToast("Network error executing confirmed action.", "danger");
    }
  };

  window.cancelAiAction = async function (actionToken, btnElement) {
    try {
      await fetch("/api/ai/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ action_token: actionToken }),
      });
      const card = document.getElementById(`actionCard_${actionToken}`);
      if (card) {
        card.className = "bg-brand-card border border-brand-border rounded-2xl p-3 text-slate-400 text-xs mt-2";
        card.innerHTML = `<span class="italic text-slate-400">Operation was cancelled.</span>`;
      }
      if (window.showToast) window.showToast("Operation cancelled.", "info");
    } catch (e) {
      console.error("Cancellation error:", e);
    }
  };

  // Clear Chat History
  async function handleClearHistory() {
    if (!window.aiSessionId) return;
    try {
      await fetch(`/api/ai/history?session_id=${encodeURIComponent(window.aiSessionId)}`, {
        method: "DELETE",
        credentials: "same-origin",
      });
      const chatLog = document.getElementById("aiChatLog");
      if (chatLog) {
        chatLog.innerHTML = `
          <div class="text-center py-4 text-xs text-slate-500 italic">
            Conversation history cleared. Start a new request anytime!
          </div>
        `;
      }
      window.aiSessionId = null;
      localStorage.removeItem("shopmanage_ai_session_id");
      if (window.showToast) window.showToast("Chat history cleared.", "info");
    } catch (e) {
      console.error("Clear history error:", e);
    }
  }

  // Auto-refresh main dashboard views when a mutation is confirmed
  function refreshMainAppViews() {
    if (typeof window.loadOverviewData === "function") window.loadOverviewData();
    if (typeof window.loadProducts === "function" && window.currentTab === "products") window.loadProducts();
    if (typeof window.loadCustomers === "function" && window.currentTab === "customers") window.loadCustomers();
    if (typeof window.loadOrders === "function" && window.currentTab === "orders") window.loadOrders();
    if (typeof window.loadInventoryMovements === "function" && window.currentTab === "inventory") window.loadInventoryMovements();
    if (typeof window.loadLowStockProducts === "function" && window.currentTab === "lowstock") window.loadLowStockProducts();
  }

  // ---------------------------------------------------------------------------
  // 5. Message Bubble Renderers
  // ---------------------------------------------------------------------------
  function appendUserBubble(container, text) {
    const bubble = document.createElement("div");
    bubble.className = "flex justify-end";
    bubble.innerHTML = `
      <div class="max-w-[85%] bg-gradient-to-r from-brand-indigoDark to-brand-cyan/90 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-xs sm:text-sm shadow-md leading-relaxed break-words">
        ${escapeHtml(text)}
      </div>
    `;
    container.appendChild(bubble);
  }

  function appendAssistantBubble(container, text, type = "normal") {
    const bubble = document.createElement("div");
    bubble.className = "ai-msg-assistant flex gap-2.5";
    
    let borderClass = "bg-brand-cardSub/80 border-brand-border/80 text-slate-200";
    let icon = "bot";
    let iconClass = "text-white bg-gradient-to-tr from-brand-indigo to-brand-cyan";

    if (type === "danger") {
      borderClass = "bg-rose-950/30 border-rose-500/40 text-rose-200";
      icon = "alert-triangle";
      iconClass = "text-white bg-rose-600";
    }

    bubble.innerHTML = `
      <div class="w-7 h-7 rounded-lg ${iconClass} flex items-center justify-center flex-shrink-0 shadow-sm mt-0.5">
        <i data-lucide="${icon}" class="w-3.5 h-3.5"></i>
      </div>
      <div class="flex-1 ${borderClass} border rounded-2xl rounded-tl-sm p-3.5 text-xs sm:text-sm shadow-sm leading-relaxed break-words space-y-1">
        ${formatMarkdownText(text)}
      </div>
    `;
    container.appendChild(bubble);
    if (window.lucide) window.lucide.createIcons({ root: bubble });
  }

  function appendLoadingBubble(container, id) {
    const bubble = document.createElement("div");
    bubble.id = id;
    bubble.className = "flex gap-2.5 items-center";
    bubble.innerHTML = `
      <div class="w-7 h-7 rounded-lg bg-gradient-to-tr from-brand-indigo to-brand-cyan flex items-center justify-center text-white flex-shrink-0 shadow-sm">
        <i data-lucide="sparkles" class="w-3.5 h-3.5 animate-spin"></i>
      </div>
      <div class="bg-brand-cardSub/80 border border-brand-border/80 rounded-2xl p-3 text-xs text-slate-400 flex items-center gap-2">
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-brand-cyan animate-bounce"></span>
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-brand-cyan animate-bounce [animation-delay:0.2s]"></span>
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-brand-cyan animate-bounce [animation-delay:0.4s]"></span>
        <span class="ml-1">Analyzing request...</span>
      </div>
    `;
    container.appendChild(bubble);
    if (window.lucide) window.lucide.createIcons({ root: bubble });
  }

  function renderDataPayloadCard(container, data) {
    if (!data || typeof data !== "object") return;
    const card = document.createElement("div");
    card.className = "bg-brand-card/90 border border-brand-cyan/30 rounded-2xl p-3 text-xs text-slate-200 mt-2 space-y-2 shadow-lg";

    // Scenario 1: Top Sales Date
    if (data.top_date !== undefined) {
      card.innerHTML = `
        <div class="font-bold text-emerald-400 flex items-center justify-between mb-1">
          <span class="flex items-center gap-1.5"><i data-lucide="trophy" class="w-4 h-4"></i> Highest Sales Date</span>
          <span class="text-[11px] text-slate-400">${escapeHtml(data.period || "All Time")}</span>
        </div>
        <div class="bg-brand-cardSub p-3 rounded-xl border border-brand-border space-y-1 text-center">
          <span class="text-xs text-slate-300 block font-semibold">${escapeHtml(data.top_date_formatted || data.top_date)}</span>
          <span class="font-extrabold text-emerald-400 text-base">৳ ${Number(data.total_sales_tk || 0).toLocaleString()}</span>
          <span class="text-[10px] text-slate-400 block">${data.orders_count || 0} Delivered &amp; Paid Orders</span>
        </div>
      `;
    }
    // Scenario 2: Sales Comparison
    else if (data.difference_tk !== undefined) {
      const isHigher = data.difference_tk > 0;
      const diffColor = isHigher ? "text-emerald-400" : (data.difference_tk < 0 ? "text-rose-400" : "text-slate-300");
      const diffSign = isHigher ? "+" : "";
      card.innerHTML = `
        <div class="font-bold text-brand-cyan flex items-center gap-1.5 mb-1">
          <i data-lucide="git-compare" class="w-4 h-4"></i>
          <span>Sales Comparison</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-center my-2">
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block">${escapeHtml(data.date_1?.label || "Date 1")}</span>
            <span class="font-bold text-white text-sm">৳ ${Number(data.date_1?.sales_tk || 0).toLocaleString()}</span>
          </div>
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block">${escapeHtml(data.date_2?.label || "Date 2")}</span>
            <span class="font-bold text-white text-sm">৳ ${Number(data.date_2?.sales_tk || 0).toLocaleString()}</span>
          </div>
        </div>
        <div class="bg-brand-cardSub/80 p-2 rounded-xl border border-brand-border text-center">
          <span class="text-[10px] text-slate-400 uppercase block">Difference</span>
          <span class="font-extrabold ${diffColor} text-sm">${diffSign}৳ ${Number(data.difference_tk || 0).toLocaleString()} ${data.percentage_change !== null ? `(${diffSign}${data.percentage_change}%)` : ""}</span>
        </div>
      `;
    }
    // Scenario 3: Top Selling Products
    else if (Array.isArray(data.products) && data.products.length > 0 && data.products[0].units_sold !== undefined) {
      let rows = data.products.slice(0, 5).map(p =>
        `<div class="flex justify-between py-1 border-b border-brand-border/40 text-xs">
          <span>#${p.rank} ${escapeHtml(p.name)} <span class="text-[10px] text-brand-cyan font-mono">(${p.sku})</span></span>
          <span class="font-bold text-emerald-400">${p.units_sold} sold (৳${Number(p.total_revenue_tk || 0).toLocaleString()})</span>
        </div>`
      ).join("");
      card.innerHTML = `
        <div class="font-bold text-amber-400 flex items-center justify-between mb-1">
          <span class="flex items-center gap-1.5"><i data-lucide="award" class="w-4 h-4"></i> Top Selling Products</span>
          <span class="text-[10px] text-slate-400">${escapeHtml(data.period || "")}</span>
        </div>
        <div>${rows}</div>
      `;
    }
    // Scenario 4: Top Customers
    else if (Array.isArray(data.customers) && data.customers.length > 0 && data.customers[0].total_spent_tk !== undefined) {
      let rows = data.customers.slice(0, 5).map(c =>
        `<div class="flex justify-between py-1 border-b border-brand-border/40 text-xs">
          <span>#${c.rank} ${escapeHtml(c.name)} <span class="text-[10px] text-slate-400">(${c.phone})</span></span>
          <span class="font-bold text-emerald-400">৳${Number(c.total_spent_tk || 0).toLocaleString()} (${c.total_orders} ord)</span>
        </div>`
      ).join("");
      card.innerHTML = `
        <div class="font-bold text-white flex items-center gap-1.5 mb-1">
          <i data-lucide="crown" class="w-4 h-4 text-amber-400"></i>
          <span>Top Customers by Spend</span>
        </div>
        <div>${rows}</div>
      `;
    }
    // Scenario A: Dashboard stats
    else if (data.total_sales_tk !== undefined) {
      card.innerHTML = `
        <div class="font-bold text-brand-cyan flex items-center gap-1.5 mb-1">
          <i data-lucide="bar-chart-3" class="w-4 h-4"></i>
          <span>Live Business Metrics</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-center">
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block uppercase">Total Revenue</span>
            <span class="font-extrabold text-emerald-400 text-sm">৳ ${data.total_sales_tk.toLocaleString()}</span>
          </div>
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block uppercase">Total Orders</span>
            <span class="font-bold text-white text-sm">${data.total_orders}</span>
          </div>
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block uppercase">Active Products</span>
            <span class="font-bold text-white text-sm">${data.total_products}</span>
          </div>
          <div class="bg-brand-cardSub p-2 rounded-xl border border-brand-border">
            <span class="text-[10px] text-slate-400 block uppercase">Low Stock Alert</span>
            <span class="font-bold text-amber-400 text-sm">${data.low_stock_items_count}</span>
          </div>
        </div>
      `;
    } 
    // Scenario B: Low stock products
    else if (Array.isArray(data.low_stock_products) && data.low_stock_products.length > 0) {
      let rows = data.low_stock_products.slice(0, 5).map(p => 
        `<div class="flex justify-between py-1 border-b border-brand-border/40 text-xs">
          <span>${escapeHtml(p.name)} <span class="font-mono text-slate-400">(${p.sku})</span></span>
          <span class="text-amber-400 font-bold">${p.current_stock} / ${p.reorder_level}</span>
        </div>`
      ).join("");

      card.innerHTML = `
        <div class="font-bold text-amber-400 flex items-center justify-between mb-1">
          <span class="flex items-center gap-1.5"><i data-lucide="alert-triangle" class="w-4 h-4"></i> Low Stock Items (${data.count})</span>
          <button onclick="if(window.switchTab) window.switchTab('lowstock')" class="text-[11px] underline text-brand-cyan">View Tab</button>
        </div>
        <div>${rows}</div>
      `;
    }
    // Scenario C: Products search
    else if (Array.isArray(data.products) && data.products.length > 0) {
      let rows = data.products.slice(0, 4).map(p =>
        `<div class="flex justify-between py-1 border-b border-brand-border/40 text-xs">
          <span>${escapeHtml(p.name)} <span class="text-[10px] text-brand-cyan font-mono">${p.sku}</span></span>
          <span class="font-bold">৳${p.price} (Stock: ${p.stock_quantity})</span>
        </div>`
      ).join("");
      card.innerHTML = `
        <div class="font-bold text-white flex items-center gap-1.5 mb-1">
          <i data-lucide="package" class="w-4 h-4 text-brand-cyan"></i>
          <span>Products Found (${data.count})</span>
        </div>
        <div>${rows}</div>
      `;
    }
    // Scenario D: Customers search
    else if (Array.isArray(data.customers) && data.customers.length > 0) {
      let rows = data.customers.slice(0, 4).map(c =>
        `<div class="flex justify-between py-1 border-b border-brand-border/40 text-xs">
          <span>${escapeHtml(c.name)}</span>
          <span class="text-slate-400">${c.phone}</span>
        </div>`
      ).join("");
      card.innerHTML = `
        <div class="font-bold text-white flex items-center gap-1.5 mb-1">
          <i data-lucide="users" class="w-4 h-4 text-brand-cyan"></i>
          <span>Customers Found (${data.count})</span>
        </div>
        <div>${rows}</div>
      `;
    }

    container.appendChild(card);
    if (window.lucide) window.lucide.createIcons({ root: card });
  }

  function scrollChatBottom() {
    const chatLog = document.getElementById("aiChatLog");
    if (chatLog) {
      chatLog.scrollTop = chatLog.scrollHeight;
    }
  }

  function escapeHtml(text) {
    if (!text) return "";
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatMarkdownText(text) {
    if (!text) return "";
    let safe = escapeHtml(text);
    // Bold **text**
    safe = safe.replace(/\*\*(.*?)\*\*/g, "<strong class='text-white font-semibold'>$1</strong>");
    // Code `code`
    safe = safe.replace(/`([^`]+)`/g, "<code class='bg-brand-card font-mono px-1 py-0.5 rounded text-brand-cyan text-xs'>$1</code>");
    // Bullet points
    safe = safe.replace(/^\s*[\-\*•]\s+(.*)$/gm, "<div class='flex gap-1.5'><span class='text-brand-cyan'>&bull;</span><span>$1</span></div>");
    // Line breaks
    safe = safe.replace(/\n\n/g, "<div class='h-2'></div>");
    safe = safe.replace(/\n/g, "<br/>");
    return safe;
  }
})();
