/**
 * Shop Management System - Client Application JavaScript
 * Fully reactive Vanilla JS implementation with Fetch API, Lucide icons, and Chart.js
 */

// Global State
window.currentTab = "overview";
window.salesChartInstance = null;
window.cachedProductsList = [];
window.cachedCustomersList = [];

// Pagination States
window.appState = {
  products: { page: 1, pageSize: 15, search: "", category: "ALL", totalPages: 1 },
  customers: { page: 1, pageSize: 15, search: "", totalPages: 1 },
  orders: { page: 1, pageSize: 15, search: "", status: "ALL", payment: "ALL", totalPages: 1 },
  inventory: { page: 1, pageSize: 20, search: "", type: "ALL", totalPages: 1 },
};

// -----------------------------------------------------------------------------
// Global Tab Switching (Available immediately on window)
// -----------------------------------------------------------------------------
window.switchTab = function(tabId) {
  window.currentTab = tabId;

  // Update button active styles
  document.querySelectorAll(".nav-tab-btn").forEach((btn) => {
    const isCurrent = btn.getAttribute("data-tab") === tabId;
    const icon = btn.querySelector("i, svg");

    if (isCurrent) {
      btn.classList.add("active", "bg-brand-cardSub", "text-brand-cyan");
      btn.classList.remove("text-slate-300");
      if (icon) {
        icon.classList.add("text-brand-cyan");
        icon.classList.remove("text-slate-400");
      }
    } else {
      btn.classList.remove("active", "bg-brand-cardSub", "text-brand-cyan");
      btn.classList.add("text-slate-300");
      if (icon && btn.getAttribute("data-tab") !== "lowstock") {
        icon.classList.remove("text-brand-cyan");
        icon.classList.add("text-slate-400");
      }
    }
  });

  // Hide all sections
  document.querySelectorAll(".tab-content").forEach((sec) => {
    sec.classList.add("hidden");
  });

  // Show target section
  const targetSection = document.getElementById(`tab-${tabId}`);
  if (targetSection) {
    targetSection.classList.remove("hidden");
  }

  // Update Header Titles
  const titles = {
    overview: { title: "Overview Analytics", sub: "High-level sales, inventory health, and recent operations" },
    products: { title: "Product Catalog", sub: "Manage products, pricing, categories, and stock thresholds" },
    customers: { title: "Customer Directory", sub: "Client contact records, addresses, and purchase histories" },
    orders: { title: "Sales Orders", sub: "Create customer orders with automated real-time stock deduction" },
    inventory: { title: "Inventory & Stock Tracking", sub: "Audit trail of all Stock IN, OUT, and Adjustment movements" },
    lowstock: { title: "Low Stock Alert Monitoring", sub: "Items currently at or below safety reorder thresholds" },
  };

  if (titles[tabId]) {
    const titleEl = document.getElementById("pageTitle");
    const subEl = document.getElementById("pageSubtitle");
    if (titleEl) titleEl.textContent = titles[tabId].title;
    if (subEl) subEl.textContent = titles[tabId].sub;
  }

  // Close mobile sidebar if open
  closeMobileSidebar();

  // Trigger data load for the selected tab
  if (tabId === "overview") loadOverviewData();
  else if (tabId === "products") loadProducts();
  else if (tabId === "customers") loadCustomers();
  else if (tabId === "orders") loadOrders();
  else if (tabId === "inventory") loadInventoryMovements();
  else if (tabId === "lowstock") loadLowStockProducts();

  if (window.lucide) {
    window.lucide.createIcons();
  }
};

// -----------------------------------------------------------------------------
// Mobile Sidebar Helpers
// -----------------------------------------------------------------------------
function closeMobileSidebar() {
  const sidebar = document.getElementById("appSidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  if (sidebar) sidebar.classList.add("-translate-x-full");
  if (backdrop) backdrop.classList.add("hidden");
}

function initSidebarMobile() {
  const sidebar = document.getElementById("appSidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  const openBtn = document.getElementById("openSidebarBtn");
  const closeBtn = document.getElementById("closeSidebarBtn");

  if (openBtn) {
    openBtn.addEventListener("click", () => {
      sidebar.classList.remove("-translate-x-full");
      backdrop.classList.remove("hidden");
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closeMobileSidebar);
  }

  if (backdrop) {
    backdrop.addEventListener("click", closeMobileSidebar);
  }
}

// -----------------------------------------------------------------------------
// Sign Out
// -----------------------------------------------------------------------------
function initLogout() {
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      window.showConfirmModal({
        title: "Sign Out",
        message: "Are you sure you want to sign out of your administrator account?",
        onConfirm: async () => {
          try {
            await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
          } catch (e) {
            console.error("Logout request failed:", e);
          }
          window.location.href = "/login";
        },
      });
    });
  }
}

// -----------------------------------------------------------------------------
// Preload helper for dropdowns (Products & Customers)
// -----------------------------------------------------------------------------
async function preloadDropdownData() {
  try {
    const [pRes, cRes] = await Promise.all([
      fetch("/api/products?page=1&page_size=200", { credentials: "same-origin" }),
      fetch("/api/customers?page=1&page_size=200", { credentials: "same-origin" }),
    ]);

    if (pRes.ok) {
      const pData = await pRes.json();
      window.cachedProductsList = pData.items || [];
      console.log(`[ShopManage] Preloaded ${window.cachedProductsList.length} products for dropdowns.`);
    } else {
      console.warn("Products preload failed with status:", pRes.status);
    }

    if (cRes.ok) {
      const cData = await cRes.json();
      window.cachedCustomersList = cData.items || [];
      console.log(`[ShopManage] Preloaded ${window.cachedCustomersList.length} customers for dropdowns.`);
    } else {
      console.warn("Customers preload failed with status:", cRes.status);
    }
  } catch (err) {
    console.warn("Dropdown preload notice:", err);
  }
}

// -----------------------------------------------------------------------------
// 1. Overview Analytics Tab
// -----------------------------------------------------------------------------
async function loadOverviewData() {
  try {
    const res = await fetch("/api/dashboard/stats", { credentials: "same-origin" });
    if (!res.ok) {
      console.warn("Failed to load /api/dashboard/stats, status:", res.status);
      return;
    }
    const data = await res.json();

    // 1. Update Stat Cards
    const elProd = document.getElementById("statTotalProducts");
    const elCust = document.getElementById("statTotalCustomers");
    const elOrd = document.getElementById("statTotalOrders");
    const elSales = document.getElementById("statTotalSales");
    const elLow = document.getElementById("statLowStock");

    if (elProd) elProd.textContent = data.total_products;
    if (elCust) elCust.textContent = data.total_customers;
    if (elOrd) elOrd.textContent = data.total_orders;
    if (elSales) elSales.textContent = `৳ ${Number(data.total_sales).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
    if (elLow) elLow.textContent = data.low_stock_count;

    // Sidebar Badges
    const navProd = document.getElementById("navProdCount");
    const navCust = document.getElementById("navCustCount");
    const navOrd = document.getElementById("navOrderCount");
    const navLow = document.getElementById("navLowStockBadge");

    if (navProd) navProd.textContent = data.total_products;
    if (navCust) navCust.textContent = data.total_customers;
    if (navOrd) navOrd.textContent = data.total_orders;
    if (navLow) {
      navLow.textContent = data.low_stock_count;
      if (data.low_stock_count > 0) {
        navLow.classList.remove("hidden");
      } else {
        navLow.classList.add("hidden");
      }
    }

    // 2. Render Chart safely
    try {
      renderSalesTrendChart(data.sales_chart);
    } catch (chartErr) {
      console.warn("Chart render notice:", chartErr);
    }

    // 3. Render Low Stock Quick Glance
    try {
      renderLowStockGlance();
    } catch (glanceErr) {
      console.warn("Glance render notice:", glanceErr);
    }

    // 4. Render Recent Orders Table
    try {
      renderRecentOrders(data.recent_orders);
    } catch (orderErr) {
      console.warn("Recent orders render notice:", orderErr);
    }

    if (window.lucide) {
      window.lucide.createIcons();
    }
  } catch (err) {
    console.error("Overview load error:", err);
  }
}

function renderSalesTrendChart(chartData) {
  const canvas = document.getElementById("salesTrendChart");
  if (!canvas) return;

  if (typeof Chart === "undefined") {
    console.warn("Chart.js library is not loaded yet.");
    return;
  }

  if (window.salesChartInstance) {
    window.salesChartInstance.destroy();
  }

  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, 240);
  gradient.addColorStop(0, "rgba(34, 211, 238, 0.35)");
  gradient.addColorStop(1, "rgba(34, 211, 238, 0.0)");

  Chart.defaults.font.family = "Arial, Helvetica, sans-serif";

  window.salesChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartData?.labels || ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Today"],
      datasets: [
        {
          label: "Sales Revenue (৳)",
          data: chartData?.sales || [0, 0, 0, 0, 0, 0, 0],
          borderColor: "#22D3EE",
          borderWidth: 2.5,
          pointBackgroundColor: "#22D3EE",
          pointBorderColor: "#020617",
          pointBorderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          fill: true,
          backgroundColor: gradient,
          tension: 0.35,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0F172A",
          titleColor: "#F8FAFC",
          bodyColor: "#22D3EE",
          borderColor: "#334155",
          borderWidth: 1,
          padding: 10,
          displayColors: false,
          callbacks: {
            label: (ctx) => `Revenue: ৳ ${Number(ctx.parsed.y).toLocaleString()}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(51, 65, 85, 0.25)" },
          ticks: { color: "#94A3B8", font: { size: 11 } },
        },
        y: {
          grid: { color: "rgba(51, 65, 85, 0.25)" },
          ticks: {
            color: "#94A3B8",
            font: { size: 11 },
            callback: (v) => `৳ ${v}`,
          },
        },
      },
    },
  });
}

async function renderLowStockGlance() {
  const container = document.getElementById("lowStockGlanceList");
  const countEl = document.getElementById("lowStockGlanceCount");
  if (!container) return;

  try {
    const res = await fetch("/api/dashboard/low-stock", { credentials: "same-origin" });
    if (!res.ok) return;
    const items = await res.json();

    if (countEl) countEl.textContent = `${items.length} items`;

    if (items.length === 0) {
      container.innerHTML = `
        <div class="p-4 rounded-xl bg-brand-cardSub/40 text-center text-xs text-slate-400">
          <i data-lucide="check-circle-2" class="w-5 h-5 text-emerald-400 mx-auto mb-1"></i>
          <span>Stock health optimal! No low stock items.</span>
        </div>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    container.innerHTML = items.slice(0, 5).map((p) => {
      const isOut = p.stock_quantity === 0;
      return `
        <div class="flex items-center justify-between p-2.5 rounded-xl bg-brand-cardSub/60 border border-brand-border/60 hover:border-brand-warning/30 transition-all">
          <div class="min-w-0 pr-2">
            <div class="text-xs font-semibold text-white truncate">${escapeHtml(p.name)}</div>
            <div class="text-[10px] text-slate-400 font-mono">SKU: ${escapeHtml(p.sku)} · Reorder: ${p.reorder_level}</div>
          </div>
          <div class="flex items-center gap-2 flex-shrink-0">
            <span class="text-xs font-bold px-2 py-0.5 rounded-full ${isOut ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'}">
              ${p.stock_quantity} left
            </span>
          </div>
        </div>
      `;
    }).join("");

    if (window.lucide) window.lucide.createIcons();
  } catch (e) {
    console.error("Glance error:", e);
  }
}

function renderRecentOrders(orders) {
  const tbody = document.getElementById("overviewRecentOrdersTable");
  if (!tbody) return;

  if (!orders || orders.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="text-center py-8 text-xs text-slate-400">
          No orders created yet. Click "New Order" to make your first sale.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = orders.map((o) => {
    return `
      <tr class="hover:bg-brand-cardSub/40 transition-colors">
        <td class="px-5 py-3 font-mono text-xs text-brand-cyan font-semibold">${escapeHtml(o.order_number)}</td>
        <td class="px-5 py-3 text-white font-medium">${escapeHtml(o.customer_name)}</td>
        <td class="px-5 py-3 text-xs text-slate-400">${escapeHtml(o.created_at)}</td>
        <td class="px-5 py-3 font-semibold text-white">৳ ${Number(o.total_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
        <td class="px-5 py-3">${formatOrderStatusBadge(o.order_status)}</td>
        <td class="px-5 py-3">${formatPaymentStatusBadge(o.payment_status)}</td>
        <td class="px-5 py-3 text-right">
          <button onclick="viewOrderInvoice(${o.id})" class="px-2.5 py-1 rounded-lg text-xs font-medium bg-brand-cardSub hover:bg-brand-border text-slate-300 hover:text-white border border-brand-border transition-all">
            Invoice
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

// -----------------------------------------------------------------------------
// Status Badges Formatters
// -----------------------------------------------------------------------------
function formatOrderStatusBadge(status) {
  const map = {
    Delivered: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    Shipped: "bg-sky-500/15 text-sky-400 border-sky-500/30",
    Processing: "bg-indigo-500/15 text-indigo-400 border-indigo-500/30",
    Pending: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    Cancelled: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  };
  const cls = map[status] || "bg-slate-500/15 text-slate-400 border-slate-500/30";
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${cls}">${status}</span>`;
}

function formatPaymentStatusBadge(status) {
  const map = {
    Paid: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    Partial: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    Unpaid: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  };
  const cls = map[status] || "bg-slate-500/15 text-slate-400 border-slate-500/30";
  return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${cls}">${status}</span>`;
}

// -----------------------------------------------------------------------------
// 2. Product Management Tab
// -----------------------------------------------------------------------------
function initProductsTab() {
  const searchInput = document.getElementById("prodSearchInput");
  const categorySelect = document.getElementById("prodCategorySelect");
  const form = document.getElementById("productForm");

  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        window.appState.products.search = e.target.value.trim();
        window.appState.products.page = 1;
        loadProducts();
      }, 300);
    });
  }

  if (categorySelect) {
    categorySelect.addEventListener("change", (e) => {
      window.appState.products.category = e.target.value;
      window.appState.products.page = 1;
      loadProducts();
    });
  }

  if (form) {
    form.addEventListener("submit", handleSaveProduct);
  }
}

async function loadProducts() {
  const tbody = document.getElementById("productsTableBody");
  const pagination = document.getElementById("productsPagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-xs text-slate-400">Loading catalog...</td></tr>`;

  try {
    const url = new URL("/api/products", window.location.origin);
    url.searchParams.set("page", window.appState.products.page);
    url.searchParams.set("page_size", window.appState.products.pageSize);
    if (window.appState.products.search) url.searchParams.set("search", window.appState.products.search);
    if (window.appState.products.category && window.appState.products.category !== "ALL") {
      url.searchParams.set("category", window.appState.products.category);
    }

    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load products");
    const data = await res.json();

    window.cachedProductsList = data.items || [];
    window.appState.products.totalPages = data.total_pages;

    // Update categories dropdown
    const catSelect = document.getElementById("prodCategorySelect");
    if (catSelect && data.categories) {
      const currentVal = catSelect.value;
      catSelect.innerHTML = `<option value="ALL">All Categories</option>` +
        data.categories.map((c) => `<option value="${escapeHtml(c)}" ${c === currentVal ? "selected" : ""}>${escapeHtml(c)}</option>`).join("");
    }

    if (data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-400">
            <i data-lucide="package-search" class="w-8 h-8 text-slate-500 mx-auto mb-2"></i>
            <div class="text-sm font-medium">No products found</div>
            <p class="text-xs text-slate-500 mt-0.5">Try searching with a different keyword or create a product.</p>
          </td>
        </tr>
      `;
      if (pagination) pagination.innerHTML = "";
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    tbody.innerHTML = data.items.map((p) => {
      let statusBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">In Stock</span>`;
      if (p.stock_quantity === 0) {
        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30">Out of Stock</span>`;
      } else if (p.stock_quantity <= p.reorder_level) {
        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30">Low Stock</span>`;
      }

      return `
        <tr class="hover:bg-brand-cardSub/40 transition-colors">
          <td class="px-5 py-3 font-mono text-xs text-brand-cyan font-semibold">${escapeHtml(p.sku)}</td>
          <td class="px-5 py-3 text-white font-medium">${escapeHtml(p.name)}</td>
          <td class="px-5 py-3 text-xs text-slate-300"><span class="px-2 py-0.5 rounded-md bg-brand-cardSub border border-brand-border">${escapeHtml(p.category)}</span></td>
          <td class="px-5 py-3 text-white font-semibold">৳ ${Number(p.price).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
          <td class="px-5 py-3 font-bold ${p.stock_quantity <= p.reorder_level ? 'text-brand-warning' : 'text-slate-100'}">${p.stock_quantity} units</td>
          <td class="px-5 py-3 text-xs text-slate-400 font-mono">${p.reorder_level}</td>
          <td class="px-5 py-3">${statusBadge}</td>
          <td class="px-5 py-3 text-right">
            <div class="flex items-center justify-end gap-1.5">
              <button onclick="quickStockIn(${p.id}, '${escapeHtml(p.name)}')" title="Quick Stock In" class="p-1.5 rounded-lg text-emerald-400 hover:bg-emerald-500/15 border border-transparent hover:border-emerald-500/30 transition-all">
                <i data-lucide="arrow-down-to-dot" class="w-4 h-4"></i>
              </button>
              <button onclick="openProductModal(${p.id})" title="Edit Product" class="p-1.5 rounded-lg text-slate-300 hover:text-brand-cyan hover:bg-brand-cardSub border border-transparent hover:border-brand-border transition-all">
                <i data-lucide="pencil" class="w-4 h-4"></i>
              </button>
              <button onclick="deleteProduct(${p.id}, '${escapeHtml(p.name)}')" title="Delete Product" class="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-brand-danger/10 border border-transparent hover:border-brand-danger/30 transition-all">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    renderPagination(pagination, window.appState.products, data.total, () => loadProducts());
    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-xs text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

window.openProductModal = function(productId = null) {
  const modal = document.getElementById("productModal");
  const title = document.getElementById("productModalTitle");
  const form = document.getElementById("productForm");

  form.reset();
  document.getElementById("prodEditId").value = "";

  if (productId) {
    title.textContent = "Edit Product Details";
    const prod = window.cachedProductsList.find((p) => p.id === productId);
    if (prod) {
      document.getElementById("prodEditId").value = prod.id;
      document.getElementById("prodName").value = prod.name;
      document.getElementById("prodSku").value = prod.sku;
      document.getElementById("prodCategory").value = prod.category;
      document.getElementById("prodPrice").value = prod.price;
      document.getElementById("prodStock").value = prod.stock_quantity;
      document.getElementById("prodReorder").value = prod.reorder_level;
    }
  } else {
    title.textContent = "Add New Product";
    document.getElementById("prodReorder").value = 5;
    document.getElementById("prodStock").value = 0;
  }

  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
};

window.closeProductModal = function() {
  document.getElementById("productModal").classList.add("hidden");
};

async function handleSaveProduct(e) {
  e.preventDefault();
  const editId = document.getElementById("prodEditId").value;
  const btn = document.getElementById("saveProductBtn");

  const payload = {
    name: document.getElementById("prodName").value.trim(),
    sku: document.getElementById("prodSku").value.trim().toUpperCase(),
    category: document.getElementById("prodCategory").value.trim() || "General",
    price: parseFloat(document.getElementById("prodPrice").value) || 0,
    stock_quantity: parseInt(document.getElementById("prodStock").value) || 0,
    reorder_level: parseInt(document.getElementById("prodReorder").value) || 0,
  };

  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    const url = editId ? `/api/products/${editId}` : "/api/products";
    const method = editId ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to save product.");

    window.showToast(editId ? "Product updated successfully!" : "Product created successfully!", "success");
    closeProductModal();
    loadProducts();
    loadOverviewData();
    preloadDropdownData();
  } catch (err) {
    window.showToast(err.message, "danger");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Product";
  }
}

window.deleteProduct = function(productId, productName) {
  window.showConfirmModal({
    title: "Delete Product",
    message: `Are you sure you want to delete "${productName}"? This action cannot be undone if product has no orders.`,
    onConfirm: async () => {
      try {
        const res = await fetch(`/api/products/${productId}`, { method: "DELETE", credentials: "same-origin" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to delete product.");

        window.showToast(data.message || "Product deleted successfully.", "success");
        loadProducts();
        loadOverviewData();
        preloadDropdownData();
      } catch (err) {
        window.showToast(err.message, "danger");
      }
    },
  });
};

// -----------------------------------------------------------------------------
// 3. Customer Management Tab
// -----------------------------------------------------------------------------
function initCustomersTab() {
  const searchInput = document.getElementById("custSearchInput");
  const form = document.getElementById("customerForm");

  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        window.appState.customers.search = e.target.value.trim();
        window.appState.customers.page = 1;
        loadCustomers();
      }, 300);
    });
  }

  if (form) {
    form.addEventListener("submit", handleSaveCustomer);
  }
}

async function loadCustomers() {
  const tbody = document.getElementById("customersTableBody");
  const pagination = document.getElementById("customersPagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8 text-xs text-slate-400">Loading customers...</td></tr>`;

  try {
    const url = new URL("/api/customers", window.location.origin);
    url.searchParams.set("page", window.appState.customers.page);
    url.searchParams.set("page_size", window.appState.customers.pageSize);
    if (window.appState.customers.search) url.searchParams.set("search", window.appState.customers.search);

    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load customers");
    const data = await res.json();

    window.cachedCustomersList = data.items || [];
    window.appState.customers.totalPages = data.total_pages;

    if (data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center py-12 text-slate-400">
            <i data-lucide="user-x" class="w-8 h-8 text-slate-500 mx-auto mb-2"></i>
            <div class="text-sm font-medium">No customers found</div>
            <p class="text-xs text-slate-500 mt-0.5">Click "Add Customer" to register your first client.</p>
          </td>
        </tr>
      `;
      if (pagination) pagination.innerHTML = "";
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    tbody.innerHTML = data.items.map((c) => {
      return `
        <tr class="hover:bg-brand-cardSub/40 transition-colors">
          <td class="px-5 py-3 font-semibold text-white">${escapeHtml(c.name)}</td>
          <td class="px-5 py-3 text-xs text-slate-300 font-mono">${escapeHtml(c.phone)}</td>
          <td class="px-5 py-3 text-xs text-brand-cyan">${escapeHtml(c.email || "-")}</td>
          <td class="px-5 py-3 text-xs text-slate-400 max-w-xs truncate">${escapeHtml(c.address || "-")}</td>
          <td class="px-5 py-3">
            <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-brand-indigo/15 text-brand-indigo border border-brand-indigo/30">
              ${c.orders_count} orders
            </span>
          </td>
          <td class="px-5 py-3 text-right">
            <div class="flex items-center justify-end gap-1.5">
              <button onclick="viewCustomerOrderHistory(${c.id}, '${escapeHtml(c.name)}', '${escapeHtml(c.phone)}')" title="View Orders" class="p-1.5 rounded-lg text-brand-cyan hover:bg-brand-cyan/15 border border-transparent hover:border-brand-cyan/30 transition-all">
                <i data-lucide="history" class="w-4 h-4"></i>
              </button>
              <button onclick="openCustomerModal(${c.id})" title="Edit Customer" class="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-brand-cardSub border border-transparent hover:border-brand-border transition-all">
                <i data-lucide="pencil" class="w-4 h-4"></i>
              </button>
              <button onclick="deleteCustomer(${c.id}, '${escapeHtml(c.name)}')" title="Delete Customer" class="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-brand-danger/10 border border-transparent hover:border-brand-danger/30 transition-all">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    renderPagination(pagination, window.appState.customers, data.total, () => loadCustomers());
    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-xs text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

window.openCustomerModal = function(customerId = null) {
  const modal = document.getElementById("customerModal");
  const title = document.getElementById("customerModalTitle");
  const form = document.getElementById("customerForm");

  form.reset();
  document.getElementById("custEditId").value = "";

  if (customerId) {
    title.textContent = "Edit Customer";
    const cust = window.cachedCustomersList.find((c) => c.id === customerId);
    if (cust) {
      document.getElementById("custEditId").value = cust.id;
      document.getElementById("custName").value = cust.name;
      document.getElementById("custPhone").value = cust.phone;
      document.getElementById("custEmail").value = cust.email || "";
      document.getElementById("custAddress").value = cust.address || "";
      document.getElementById("custNotes").value = cust.notes || "";
    }
  } else {
    title.textContent = "Add Customer";
  }

  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
};

window.closeCustomerModal = function() {
  document.getElementById("customerModal").classList.add("hidden");
};

async function handleSaveCustomer(e) {
  e.preventDefault();
  const editId = document.getElementById("custEditId").value;
  const btn = document.getElementById("saveCustomerBtn");

  const payload = {
    name: document.getElementById("custName").value.trim(),
    phone: document.getElementById("custPhone").value.trim(),
    email: document.getElementById("custEmail").value.trim() || null,
    address: document.getElementById("custAddress").value.trim() || null,
    notes: document.getElementById("custNotes").value.trim() || null,
  };

  btn.disabled = true;
  btn.textContent = "Saving...";

  try {
    const url = editId ? `/api/customers/${editId}` : "/api/customers";
    const method = editId ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to save customer.");

    window.showToast(editId ? "Customer updated successfully!" : "Customer created successfully!", "success");
    closeCustomerModal();
    loadCustomers();
    loadOverviewData();
    preloadDropdownData();
  } catch (err) {
    window.showToast(err.message, "danger");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Customer";
  }
}

window.deleteCustomer = function(customerId, customerName) {
  window.showConfirmModal({
    title: "Delete Customer",
    message: `Are you sure you want to delete "${customerName}"?`,
    onConfirm: async () => {
      try {
        const res = await fetch(`/api/customers/${customerId}`, { method: "DELETE", credentials: "same-origin" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to delete customer.");

        window.showToast(data.message || "Customer deleted successfully.", "success");
        loadCustomers();
        loadOverviewData();
        preloadDropdownData();
      } catch (err) {
        window.showToast(err.message, "danger");
      }
    },
  });
};

window.viewCustomerOrderHistory = async function(customerId, customerName, customerPhone) {
  const modal = document.getElementById("customerHistoryModal");
  const nameEl = document.getElementById("historyModalCustName");
  const detailEl = document.getElementById("historyModalCustDetails");
  const listEl = document.getElementById("customerHistoryList");

  nameEl.textContent = `${customerName}'s Order History`;
  detailEl.textContent = `Phone: ${customerPhone}`;
  listEl.innerHTML = `<div class="text-center py-6 text-xs text-slate-400">Loading order records...</div>`;
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`/api/customers/${customerId}/orders`, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to fetch order history.");
    const orders = await res.json();

    if (orders.length === 0) {
      listEl.innerHTML = `
        <div class="p-6 rounded-xl bg-brand-cardSub/40 text-center text-xs text-slate-400">
          This customer has not placed any orders yet.
        </div>
      `;
      return;
    }

    listEl.innerHTML = orders.map((o) => {
      return `
        <div class="p-4 rounded-xl bg-brand-cardSub/70 border border-brand-border space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="font-mono font-bold text-brand-cyan">${escapeHtml(o.order_number)}</span>
            <span class="text-slate-400">${new Date(o.created_at).toLocaleDateString()}</span>
          </div>
          <div class="flex items-center justify-between text-xs pt-1">
            <div class="flex items-center gap-2">
              ${formatOrderStatusBadge(o.order_status)}
              ${formatPaymentStatusBadge(o.payment_status)}
            </div>
            <div class="text-sm font-extrabold text-white">৳ ${o.total_amount.toLocaleString("en-US", { minimumFractionDigits: 2 })}</div>
          </div>
          <div class="text-[11px] text-slate-400 border-t border-brand-border/60 pt-2 mt-2">
            Items: ${o.items.map(it => `${escapeHtml(it.product_name)} (x${it.quantity})`).join(", ")}
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    listEl.innerHTML = `<div class="text-center py-4 text-xs text-rose-400">${escapeHtml(err.message)}</div>`;
  }
};

window.closeCustomerHistoryModal = function() {
  document.getElementById("customerHistoryModal").classList.add("hidden");
};

// -----------------------------------------------------------------------------
// 4. Order Management Tab
// -----------------------------------------------------------------------------
function initOrdersTab() {
  const searchInput = document.getElementById("orderSearchInput");
  const statusFilter = document.getElementById("orderStatusFilter");
  const paymentFilter = document.getElementById("orderPaymentFilter");
  const addItemRowBtn = document.getElementById("addOrderItemRowBtn");
  const orderForm = document.getElementById("orderForm");
  const statusForm = document.getElementById("orderStatusForm");

  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        window.appState.orders.search = e.target.value.trim();
        window.appState.orders.page = 1;
        loadOrders();
      }, 300);
    });
  }

  if (statusFilter) {
    statusFilter.addEventListener("change", (e) => {
      window.appState.orders.status = e.target.value;
      window.appState.orders.page = 1;
      loadOrders();
    });
  }

  if (paymentFilter) {
    paymentFilter.addEventListener("change", (e) => {
      window.appState.orders.payment = e.target.value;
      window.appState.orders.page = 1;
      loadOrders();
    });
  }

  if (addItemRowBtn) {
    addItemRowBtn.addEventListener("click", () => addOrderItemRow());
  }

  if (orderForm) {
    orderForm.addEventListener("submit", handleSaveOrder);
  }

  if (statusForm) {
    statusForm.addEventListener("submit", handleSaveOrderStatus);
  }
}

async function loadOrders() {
  const tbody = document.getElementById("ordersTableBody");
  const pagination = document.getElementById("ordersPagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-xs text-slate-400">Loading orders...</td></tr>`;

  try {
    const url = new URL("/api/orders", window.location.origin);
    url.searchParams.set("page", window.appState.orders.page);
    url.searchParams.set("page_size", window.appState.orders.pageSize);
    if (window.appState.orders.search) url.searchParams.set("search", window.appState.orders.search);
    if (window.appState.orders.status && window.appState.orders.status !== "ALL") url.searchParams.set("order_status", window.appState.orders.status);
    if (window.appState.orders.payment && window.appState.orders.payment !== "ALL") url.searchParams.set("payment_status", window.appState.orders.payment);

    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load orders");
    const data = await res.json();

    window.appState.orders.totalPages = data.total_pages;

    if (data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-400">
            <i data-lucide="shopping-cart" class="w-8 h-8 text-slate-500 mx-auto mb-2"></i>
            <div class="text-sm font-medium">No orders found</div>
            <p class="text-xs text-slate-500 mt-0.5">Click "Create New Order" to start selling.</p>
          </td>
        </tr>
      `;
      if (pagination) pagination.innerHTML = "";
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    tbody.innerHTML = data.items.map((o) => {
      const itemsCount = o.items ? o.items.length : 0;
      const dateStr = new Date(o.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

      return `
        <tr class="hover:bg-brand-cardSub/40 transition-colors">
          <td class="px-5 py-3 font-mono text-xs text-brand-cyan font-bold">${escapeHtml(o.order_number)}</td>
          <td class="px-5 py-3">
            <div class="text-white font-medium">${escapeHtml(o.customer_name)}</div>
            <div class="text-[11px] text-slate-400 font-mono">${escapeHtml(o.customer_phone)}</div>
          </td>
          <td class="px-5 py-3 text-xs text-slate-400">${dateStr}</td>
          <td class="px-5 py-3 text-xs text-slate-300">${itemsCount} items</td>
          <td class="px-5 py-3 font-bold text-white">৳ ${Number(o.total_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
          <td class="px-5 py-3">${formatOrderStatusBadge(o.order_status)}</td>
          <td class="px-5 py-3">${formatPaymentStatusBadge(o.payment_status)}</td>
          <td class="px-5 py-3 text-right">
            <div class="flex items-center justify-end gap-1.5">
              <button onclick="viewOrderInvoice(${o.id})" title="Print Invoice" class="p-1.5 rounded-lg text-brand-cyan hover:bg-brand-cyan/15 border border-transparent hover:border-brand-cyan/30 transition-all">
                <i data-lucide="receipt" class="w-4 h-4"></i>
              </button>
              <button onclick="openOrderStatusModal(${o.id}, '${o.order_number}', '${o.order_status}', '${o.payment_status}', '${escapeHtml(o.notes || '')}')" title="Change Status" class="p-1.5 rounded-lg text-slate-300 hover:text-white hover:bg-brand-cardSub border border-transparent hover:border-brand-border transition-all">
                <i data-lucide="sliders" class="w-4 h-4"></i>
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    renderPagination(pagination, window.appState.orders, data.total, () => loadOrders());
    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-xs text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

window.openCreateOrderModal = async function() {
  const modal = document.getElementById("orderModal");
  const custSelect = document.getElementById("orderCustomerSelect");
  const container = document.getElementById("orderItemsContainer");
  const grandTotal = document.getElementById("orderGrandTotal");

  await preloadDropdownData();

  if (window.cachedCustomersList.length === 0) {
    window.showToast("Please add at least one customer before creating an order.", "warning");
    switchTab("customers");
    openCustomerModal();
    return;
  }

  if (window.cachedProductsList.length === 0) {
    window.showToast("Please add at least one product before creating an order.", "warning");
    switchTab("products");
    openProductModal();
    return;
  }

  custSelect.innerHTML = window.cachedCustomersList.map((c) => {
    return `<option value="${c.id}">${escapeHtml(c.name)} (${escapeHtml(c.phone)})</option>`;
  }).join("");

  container.innerHTML = "";
  addOrderItemRow();
  grandTotal.textContent = "৳ 0.00";

  document.getElementById("orderForm").reset();
  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
};

window.closeOrderModal = function() {
  document.getElementById("orderModal").classList.add("hidden");
};

function addOrderItemRow() {
  const container = document.getElementById("orderItemsContainer");
  const rowId = "itemRow_" + Math.random().toString(36).substr(2, 9);

  const row = document.createElement("div");
  row.className = "flex items-center gap-2 p-2 rounded-lg bg-brand-cardSub/60 border border-brand-border/60 text-xs item-row";
  row.id = rowId;

  const prodOptions = window.cachedProductsList.map((p) => {
    return `<option value="${p.id}" data-price="${p.price}" data-stock="${p.stock_quantity}">${escapeHtml(p.name)} (Stock: ${p.stock_quantity}) - ৳${p.price}</option>`;
  }).join("");

  row.innerHTML = `
    <div class="flex-1 min-w-[200px]">
      <select class="w-full px-2.5 py-1.5 bg-brand-card border border-brand-border rounded-lg text-xs text-white focus:outline-none focus:border-brand-cyan item-product-select">
        ${prodOptions}
      </select>
    </div>
    <div class="w-20">
      <input type="number" min="1" value="1" class="w-full px-2 py-1.5 bg-brand-card border border-brand-border rounded-lg text-xs text-white focus:outline-none focus:border-brand-cyan item-quantity-input">
    </div>
    <div class="w-28 text-right font-bold text-brand-cyan item-line-total">
      ৳ 0.00
    </div>
    <button type="button" onclick="removeOrderItemRow('${rowId}')" class="p-1 text-slate-400 hover:text-rose-400 rounded">
      ✕
    </button>
  `;

  container.appendChild(row);

  const selectEl = row.querySelector(".item-product-select");
  const qtyEl = row.querySelector(".item-quantity-input");

  selectEl.addEventListener("change", () => recalculateOrderTotals());
  qtyEl.addEventListener("input", () => recalculateOrderTotals());

  recalculateOrderTotals();
  if (window.lucide) window.lucide.createIcons();
}

window.removeOrderItemRow = function(rowId) {
  const row = document.getElementById(rowId);
  if (row) {
    const container = document.getElementById("orderItemsContainer");
    if (container.querySelectorAll(".item-row").length <= 1) {
      window.showToast("An order must have at least one product.", "warning");
      return;
    }
    row.remove();
    recalculateOrderTotals();
  }
};

function recalculateOrderTotals() {
  const container = document.getElementById("orderItemsContainer");
  const rows = container.querySelectorAll(".item-row");
  let grandTotal = 0;

  rows.forEach((r) => {
    const select = r.querySelector(".item-product-select");
    const qtyInput = r.querySelector(".item-quantity-input");
    const lineTotalEl = r.querySelector(".item-line-total");

    const selectedOpt = select.options[select.selectedIndex];
    const unitPrice = parseFloat(selectedOpt?.getAttribute("data-price") || 0);
    const availableStock = parseInt(selectedOpt?.getAttribute("data-stock") || 0);
    const qty = parseInt(qtyInput.value) || 0;

    if (qty > availableStock) {
      qtyInput.classList.add("border-rose-500", "text-rose-400");
    } else {
      qtyInput.classList.remove("border-rose-500", "text-rose-400");
    }

    const lineTotal = unitPrice * qty;
    lineTotalEl.textContent = `৳ ${lineTotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
    grandTotal += lineTotal;
  });

  const totalEl = document.getElementById("orderGrandTotal");
  if (totalEl) {
    totalEl.textContent = `৳ ${grandTotal.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
  }
}

async function handleSaveOrder(e) {
  e.preventDefault();
  const btn = document.getElementById("saveOrderBtn");
  const customerId = parseInt(document.getElementById("orderCustomerSelect").value);
  const orderStatus = document.getElementById("orderStatusSelect").value;
  const paymentStatus = document.getElementById("orderPaymentSelect").value;
  const notes = document.getElementById("orderNotes").value.trim() || null;

  const rows = document.querySelectorAll("#orderItemsContainer .item-row");
  const items = [];

  for (const r of rows) {
    const select = r.querySelector(".item-product-select");
    const qtyInput = r.querySelector(".item-quantity-input");
    const pid = parseInt(select.value);
    const qty = parseInt(qtyInput.value);

    if (!qty || qty <= 0) {
      window.showToast("Item quantity must be greater than zero.", "danger");
      return;
    }
    items.push({ product_id: pid, quantity: qty });
  }

  if (items.length === 0) {
    window.showToast("Please add at least one item to order.", "warning");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Processing Order & Stock...";

  try {
    const res = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: customerId,
        order_status: orderStatus,
        payment_status: paymentStatus,
        notes,
        items,
      }),
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to create order.");

    window.showToast(`Order #${data.order_number} created! Stock deducted.`, "success");
    closeOrderModal();
    loadOrders();
    loadOverviewData();
    preloadDropdownData();

    viewOrderInvoice(data.id);
  } catch (err) {
    window.showToast(err.message, "danger");
  } finally {
    btn.disabled = false;
    btn.textContent = "Place Order & Deduct Stock";
  }
}

window.openOrderStatusModal = function(orderId, orderNum, orderStatus, paymentStatus, notes) {
  const modal = document.getElementById("orderStatusModal");
  document.getElementById("updateStatusModalOrderNum").textContent = `Order ${orderNum}`;
  document.getElementById("statusOrderId").value = orderId;
  document.getElementById("editOrderStatus").value = orderStatus;
  document.getElementById("editPaymentStatus").value = paymentStatus;
  document.getElementById("editOrderNotes").value = notes || "";
  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
};

window.closeOrderStatusModal = function() {
  document.getElementById("orderStatusModal").classList.add("hidden");
};

async function handleSaveOrderStatus(e) {
  e.preventDefault();
  const orderId = document.getElementById("statusOrderId").value;
  const orderStatus = document.getElementById("editOrderStatus").value;
  const paymentStatus = document.getElementById("editPaymentStatus").value;
  const notes = document.getElementById("editOrderNotes").value.trim() || null;

  try {
    const res = await fetch(`/api/orders/${orderId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_status: orderStatus,
        payment_status: paymentStatus,
        notes,
      }),
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update order status.");

    window.showToast("Order status updated! Stock auto-synced.", "success");
    closeOrderStatusModal();
    loadOrders();
    loadOverviewData();
  } catch (err) {
    window.showToast(err.message, "danger");
  }
}

window.currentInvoiceData = null;

window.viewOrderInvoice = async function(orderId) {
  const modal = document.getElementById("invoiceModal");
  modal.classList.remove("hidden");

  try {
    const res = await fetch(`/api/orders/${orderId}/invoice`, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load invoice.");
    const inv = await res.json();
    window.currentInvoiceData = inv;

    document.getElementById("invNumber").textContent = inv.invoice_number;
    document.getElementById("invDate").textContent = inv.date;
    document.getElementById("invCustName").textContent = inv.customer.name;
    document.getElementById("invCustPhone").textContent = `Phone: ${inv.customer.phone || "-"}`;
    document.getElementById("invCustEmail").textContent = `Email: ${inv.customer.email || "-"}`;
    document.getElementById("invCustAddress").textContent = `Address: ${inv.customer.address || "-"}`;
    document.getElementById("invOrderStatus").textContent = inv.order_status;
    document.getElementById("invPaymentStatus").textContent = inv.payment_status;
    document.getElementById("invNotes").textContent = inv.notes || "Thank you for your business!";
    document.getElementById("invGrandTotal").textContent = `৳ ${inv.total_amount.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

    const tbody = document.getElementById("invItemsTable");
    tbody.innerHTML = inv.items.map((it) => {
      return `
        <tr class="border-b border-brand-border/60">
          <td class="p-3 font-semibold text-white">${escapeHtml(it.name)}</td>
          <td class="p-3 text-center font-mono text-slate-400">${escapeHtml(it.sku)}</td>
          <td class="p-3 text-right">৳ ${Number(it.unit_price).toFixed(2)}</td>
          <td class="p-3 text-center font-bold text-white">${it.quantity}</td>
          <td class="p-3 text-right font-bold text-brand-cyan">৳ ${Number(it.line_total).toFixed(2)}</td>
        </tr>
      `;
    }).join("");

    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    window.showToast(err.message, "danger");
  }
};

window.closeInvoiceModal = function() {
  document.getElementById("invoiceModal").classList.add("hidden");
};

// Dedicated, pixel-perfect invoice printing engine
window.printInvoice = function() {
  const inv = window.currentInvoiceData;

  const invNumber = inv?.invoice_number || document.getElementById("invNumber")?.textContent || "INV-000";
  const invDate = inv?.date || document.getElementById("invDate")?.textContent || "";
  const custName = inv?.customer?.name || document.getElementById("invCustName")?.textContent || "Valued Customer";
  const custPhone = inv?.customer?.phone ? `Phone: ${inv.customer.phone}` : (document.getElementById("invCustPhone")?.textContent || "");
  const custEmail = inv?.customer?.email ? `Email: ${inv.customer.email}` : (document.getElementById("invCustEmail")?.textContent || "");
  const custAddress = inv?.customer?.address ? `Address: ${inv.customer.address}` : (document.getElementById("invCustAddress")?.textContent || "");
  const orderStatus = inv?.order_status || document.getElementById("invOrderStatus")?.textContent || "Completed";
  const paymentStatus = inv?.payment_status || document.getElementById("invPaymentStatus")?.textContent || "Paid";
  const grandTotal = inv ? `৳ ${Number(inv.total_amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}` : (document.getElementById("invGrandTotal")?.textContent || "৳ 0.00");
  const notes = inv?.notes || document.getElementById("invNotes")?.textContent || "Thank you for your business!";

  let itemsRowsHtml = "";
  if (inv && Array.isArray(inv.items) && inv.items.length > 0) {
    itemsRowsHtml = inv.items.map((it) => `
      <tr>
        <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #0f172a;">${escapeHtml(it.name)}</td>
        <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: center; font-family: monospace; color: #64748b; font-size: 11px;">${escapeHtml(it.sku)}</td>
        <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right; color: #334155;">৳ ${Number(it.unit_price).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
        <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: #0f172a;">${it.quantity}</td>
        <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold; color: #0284c7;">৳ ${Number(it.line_total).toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
      </tr>
    `).join("");
  } else {
    const rows = document.querySelectorAll("#invItemsTable tr");
    if (rows && rows.length > 0) {
      itemsRowsHtml = Array.from(rows).map(row => {
        const cells = Array.from(row.querySelectorAll("td"));
        return `
          <tr>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #0f172a;">${cells[0]?.textContent || ""}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: center; font-family: monospace; color: #64748b; font-size: 11px;">${cells[1]?.textContent || ""}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right; color: #334155;">${cells[2]?.textContent || ""}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: center; font-weight: bold; color: #0f172a;">${cells[3]?.textContent || ""}</td>
            <td style="padding: 10px 12px; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold; color: #0284c7;">${cells[4]?.textContent || ""}</td>
          </tr>
        `;
      }).join("");
    }
  }

  // Create or reuse hidden iframe for isolated clean printing
  let printFrame = document.getElementById("invoicePrintFrame");
  if (!printFrame) {
    printFrame = document.createElement("iframe");
    printFrame.id = "invoicePrintFrame";
    printFrame.style.position = "fixed";
    printFrame.style.right = "0";
    printFrame.style.bottom = "0";
    printFrame.style.width = "0";
    printFrame.style.height = "0";
    printFrame.style.border = "none";
    document.body.appendChild(printFrame);
  }

  const frameDoc = printFrame.contentWindow.document;
  frameDoc.open();
  frameDoc.write(`<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>${escapeHtml(invNumber)} - Commercial Invoice</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif; }
    body { padding: 36px 40px; color: #0f172a; background: #ffffff; font-size: 13px; line-height: 1.5; }
    .header { display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 20px; border-bottom: 2px solid #e2e8f0; margin-bottom: 24px; }
    .brand-box { display: flex; align-items: center; gap: 12px; }
    .brand-icon { width: 38px; height: 38px; border-radius: 8px; background: #0284c7; color: #ffffff; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: bold; }
    .brand-name { font-size: 24px; font-weight: 800; color: #0f172a; letter-spacing: -0.5px; }
    .brand-name span { color: #0284c7; }
    .brand-sub { font-size: 11px; color: #64748b; margin-top: 2px; }
    .inv-meta { text-align: right; }
    .inv-num { font-size: 16px; font-weight: 800; color: #0284c7; letter-spacing: 0.5px; }
    .inv-date { font-size: 12px; color: #64748b; margin-top: 3px; }
    
    .info-grid { display: flex; justify-content: space-between; margin-bottom: 24px; }
    .info-col { width: 48%; }
    .section-title { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px; }
    .cust-title { font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 3px; }
    .info-line { font-size: 12px; color: #475569; margin-bottom: 2px; }
    
    .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; }
    .badge-paid { background: #dcfce7; color: #15803d; }
    .badge-unpaid { background: #fef3c7; color: #b45309; }
    .badge-status { background: #e0f2fe; color: #0369a1; }
    
    .table-container { width: 100%; border: 1px solid #cbd5e1; border-radius: 8px; overflow: hidden; margin-bottom: 24px; }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { background: #f8fafc; color: #334155; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; padding: 10px 12px; border-bottom: 1px solid #cbd5e1; }
    td { padding: 10px 12px; border-bottom: 1px solid #e2e8f0; font-size: 12px; color: #1e293b; }
    tr:last-child td { border-bottom: none; }
    .text-center { text-align: center; }
    .text-right { text-align: right; }
    
    .footer-grid { display: flex; justify-content: space-between; align-items: flex-end; padding-top: 18px; border-top: 2px solid #e2e8f0; }
    .notes-box { max-width: 60%; }
    .notes-label { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; margin-bottom: 4px; }
    .notes-text { font-size: 12px; color: #475569; font-style: italic; }
    .total-box { text-align: right; }
    .total-label { font-size: 12px; color: #64748b; font-weight: 600; margin-bottom: 2px; }
    .total-amount { font-size: 26px; font-weight: 900; color: #0284c7; }

    @media print {
      @page { margin: 12mm 15mm; size: A4 portrait; }
      body { padding: 0; }
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="brand-box">
      <div class="brand-icon">S</div>
      <div>
        <div class="brand-name">Shop<span>Manage</span></div>
        <div class="brand-sub">Enterprise Cloud POS & Inventory System</div>
      </div>
    </div>
    <div class="inv-meta">
      <div class="inv-num">${escapeHtml(invNumber)}</div>
      <div class="inv-date">${escapeHtml(invDate)}</div>
    </div>
  </div>

  <div class="info-grid">
    <div class="info-col">
      <div class="section-title">Billed To</div>
      <div class="cust-title">${escapeHtml(custName)}</div>
      <div class="info-line">${escapeHtml(custPhone)}</div>
      <div class="info-line">${escapeHtml(custEmail)}</div>
      <div class="info-line">${escapeHtml(custAddress)}</div>
    </div>
    <div class="info-col" style="text-align: right;">
      <div class="section-title">Order Summary</div>
      <div class="info-line">Order Status: <span class="badge badge-status">${escapeHtml(orderStatus)}</span></div>
      <div class="info-line" style="margin-top: 5px;">Payment: <span class="badge ${paymentStatus.toLowerCase().includes('paid') && !paymentStatus.toLowerCase().includes('unpaid') ? 'badge-paid' : 'badge-unpaid'}">${escapeHtml(paymentStatus)}</span></div>
    </div>
  </div>

  <div class="table-container">
    <table>
      <thead>
        <tr>
          <th>Item Description</th>
          <th class="text-center">SKU</th>
          <th class="text-right">Unit Price</th>
          <th class="text-center">Qty</th>
          <th class="text-right">Line Total</th>
        </tr>
      </thead>
      <tbody>
        ${itemsRowsHtml}
      </tbody>
    </table>
  </div>

  <div class="footer-grid">
    <div class="notes-box">
      <div class="notes-label">Remarks / Instructions</div>
      <div class="notes-text">${escapeHtml(notes)}</div>
    </div>
    <div class="total-box">
      <div class="total-label">Grand Total</div>
      <div class="total-amount">${escapeHtml(grandTotal)}</div>
    </div>
  </div>
</body>
</html>`);
  frameDoc.close();

  setTimeout(() => {
    try {
      printFrame.contentWindow.focus();
      printFrame.contentWindow.print();
    } catch (e) {
      console.warn("Iframe print fallback to window.print():", e);
      window.print();
    }
  }, 250);
};

// -----------------------------------------------------------------------------
// 5. Inventory & Stock Movement Tab
// -----------------------------------------------------------------------------
function initInventoryTab() {
  const searchInput = document.getElementById("inventorySearchInput");
  const typeFilter = document.getElementById("movementTypeFilter");
  const form = document.getElementById("stockForm");

  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        window.appState.inventory.search = e.target.value.trim();
        window.appState.inventory.page = 1;
        loadInventoryMovements();
      }, 300);
    });
  }

  if (typeFilter) {
    typeFilter.addEventListener("change", (e) => {
      window.appState.inventory.type = e.target.value;
      window.appState.inventory.page = 1;
      loadInventoryMovements();
    });
  }

  if (form) {
    form.addEventListener("submit", handleSaveStockMovement);
  }
}

async function loadInventoryMovements() {
  const tbody = document.getElementById("inventoryTableBody");
  const pagination = document.getElementById("inventoryPagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" class="text-center py-8 text-xs text-slate-400">Loading audit history...</td></tr>`;

  try {
    const url = new URL("/api/inventory/movements", window.location.origin);
    url.searchParams.set("page", window.appState.inventory.page);
    url.searchParams.set("page_size", window.appState.inventory.pageSize);
    if (window.appState.inventory.search) url.searchParams.set("search", window.appState.inventory.search);
    if (window.appState.inventory.type && window.appState.inventory.type !== "ALL") url.searchParams.set("movement_type", window.appState.inventory.type);

    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load inventory movements");
    const data = await res.json();

    window.appState.inventory.totalPages = data.total_pages;

    if (data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center py-12 text-slate-400">
            <i data-lucide="archive" class="w-8 h-8 text-slate-500 mx-auto mb-2"></i>
            <div class="text-sm font-medium">No stock movements recorded</div>
            <p class="text-xs text-slate-500 mt-0.5">Movements are generated when receiving stock or placing orders.</p>
          </td>
        </tr>
      `;
      if (pagination) pagination.innerHTML = "";
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    tbody.innerHTML = data.items.map((m) => {
      let typeBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">STOCK IN</span>`;
      if (m.movement_type === "OUT") {
        typeBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-500/15 text-rose-400 border border-rose-500/30">STOCK OUT</span>`;
      } else if (m.movement_type === "ADJUSTMENT") {
        typeBadge = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">ADJUSTMENT</span>`;
      }

      const dateStr = new Date(m.created_at).toLocaleString("en-US", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      });

      return `
        <tr class="hover:bg-brand-cardSub/40 transition-colors">
          <td class="px-5 py-3 text-xs text-slate-400 font-mono">${dateStr}</td>
          <td class="px-5 py-3">
            <div class="text-white font-medium">${escapeHtml(m.product_name)}</div>
            <div class="text-[11px] text-brand-cyan font-mono">${escapeHtml(m.product_sku)}</div>
          </td>
          <td class="px-5 py-3">${typeBadge}</td>
          <td class="px-5 py-3 font-extrabold text-white">${m.quantity}</td>
          <td class="px-5 py-3 text-xs font-mono">
            <span class="text-slate-400">${m.previous_stock}</span>
            <span class="text-slate-500 mx-1">→</span>
            <span class="text-brand-cyan font-bold">${m.new_stock}</span>
          </td>
          <td class="px-5 py-3 text-xs text-slate-300 max-w-sm">${escapeHtml(m.reason || "-")}</td>
          <td class="px-5 py-3 text-xs text-slate-400">${escapeHtml(m.user_name || "System")}</td>
        </tr>
      `;
    }).join("");

    renderPagination(pagination, window.appState.inventory, data.total, () => loadInventoryMovements());
    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-6 text-xs text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

window.openStockModal = async function(preselectedProductId = null, preselectedType = "IN") {
  const modal = document.getElementById("stockModal");
  const prodSelect = document.getElementById("stockProductSelect");
  const typeSelect = document.getElementById("stockMovementType");
  const form = document.getElementById("stockForm");

  form.reset();

  // If products are not cached yet, load them now
  if (!window.cachedProductsList || window.cachedProductsList.length === 0) {
    await preloadDropdownData();
  }

  if (window.cachedProductsList && window.cachedProductsList.length > 0) {
    prodSelect.innerHTML = window.cachedProductsList.map((p) => {
      const isSelected = preselectedProductId && String(p.id) === String(preselectedProductId);
      return `<option value="${p.id}" ${isSelected ? "selected" : ""}>${escapeHtml(p.name)} (SKU: ${escapeHtml(p.sku)}) · Stock: ${p.stock_quantity}</option>`;
    }).join("");

    if (preselectedProductId) {
      prodSelect.value = String(preselectedProductId);
    }
  } else {
    prodSelect.innerHTML = `<option value="">No products found. Please add products first.</option>`;
  }

  typeSelect.value = preselectedType;
  document.getElementById("stockQuantity").value = 10;
  modal.classList.remove("hidden");
  if (window.lucide) window.lucide.createIcons();
};

window.closeStockModal = function() {
  document.getElementById("stockModal").classList.add("hidden");
};

window.quickStockIn = async function(productId, productName) {
  await window.openStockModal(productId, "IN");
  const reasonEl = document.getElementById("stockReason");
  if (reasonEl) {
    reasonEl.value = `Restocked ${productName}`;
  }
};

async function handleSaveStockMovement(e) {
  e.preventDefault();
  const btn = document.getElementById("saveStockBtn");
  const productId = parseInt(document.getElementById("stockProductSelect").value);
  const movementType = document.getElementById("stockMovementType").value;
  const quantity = parseInt(document.getElementById("stockQuantity").value);
  const reason = document.getElementById("stockReason").value.trim() || null;

  btn.disabled = true;
  btn.textContent = "Updating Stock...";

  try {
    const res = await fetch("/api/inventory/movement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: productId,
        movement_type: movementType,
        quantity,
        reason,
      }),
      credentials: "same-origin",
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to execute stock movement.");

    window.showToast(`Stock updated! New stock is ${data.new_stock} units.`, "success");
    closeStockModal();
    loadInventoryMovements();
    loadProducts();
    loadOverviewData();
    if (window.currentTab === "lowstock") loadLowStockProducts();
  } catch (err) {
    window.showToast(err.message, "danger");
  } finally {
    btn.disabled = false;
    btn.textContent = "Execute Movement";
  }
}

// -----------------------------------------------------------------------------
// 6. Low Stock Tab
// -----------------------------------------------------------------------------
async function loadLowStockProducts() {
  const tbody = document.getElementById("lowStockTableBody");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-xs text-slate-400">Scanning inventory thresholds...</td></tr>`;

  try {
    const res = await fetch("/api/dashboard/low-stock", { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to load low stock inventory.");
    const products = await res.json();

    if (products.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-400">
            <i data-lucide="shield-check" class="w-10 h-10 text-emerald-400 mx-auto mb-2"></i>
            <div class="text-sm font-bold text-white">All stock levels are optimal!</div>
            <p class="text-xs text-slate-500 mt-0.5">No products currently need restocking.</p>
          </td>
        </tr>
      `;
      if (window.lucide) window.lucide.createIcons();
      return;
    }

    tbody.innerHTML = products.map((p) => {
      const isOut = p.stock_quantity === 0;
      const ratio = p.reorder_level > 0 ? Math.min(100, Math.round((p.stock_quantity / p.reorder_level) * 100)) : 0;
      const barColor = isOut ? "bg-rose-500" : "bg-amber-500";

      return `
        <tr class="hover:bg-brand-cardSub/40 transition-colors">
          <td class="px-5 py-3 font-semibold text-white">${escapeHtml(p.name)}</td>
          <td class="px-5 py-3 font-mono text-xs text-brand-cyan">${escapeHtml(p.sku)}</td>
          <td class="px-5 py-3 text-xs text-slate-400">${escapeHtml(p.category)}</td>
          <td class="px-5 py-3 font-extrabold ${isOut ? 'text-rose-400' : 'text-amber-400'}">${p.stock_quantity} units</td>
          <td class="px-5 py-3 text-xs font-mono text-slate-300">${p.reorder_level} units</td>
          <td class="px-5 py-3 w-40">
            <div class="flex items-center gap-2">
              <div class="flex-1 h-2 rounded-full bg-brand-cardSub overflow-hidden">
                <div class="h-full ${barColor}" style="width: ${ratio}%"></div>
              </div>
              <span class="text-[10px] text-slate-400 font-mono">${ratio}%</span>
            </div>
          </td>
          <td class="px-5 py-3">
            ${isOut ? '<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-500/20 text-rose-400 border border-rose-500/40">DANGER: 0 STOCK</span>' : '<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/40">WARNING: LOW</span>'}
          </td>
          <td class="px-5 py-3 text-right">
            <button onclick="quickStockIn(${p.id}, '${escapeHtml(p.name)}')" class="px-3 py-1.5 rounded-xl text-xs font-semibold text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 shadow-md shadow-emerald-900/30 transition-all flex items-center gap-1.5 ml-auto">
              <i data-lucide="plus" class="w-3.5 h-3.5"></i>
              <span>Stock In</span>
            </button>
          </td>
        </tr>
      `;
    }).join("");

    if (window.lucide) window.lucide.createIcons();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-xs text-rose-400">${escapeHtml(err.message)}</td></tr>`;
  }
}

// -----------------------------------------------------------------------------
// Pagination Rendering Helper
// -----------------------------------------------------------------------------
function renderPagination(container, pageState, totalItems, onPageChange) {
  if (!container) return;

  const current = pageState.page;
  const totalPages = Math.max(1, pageState.totalPages);

  container.innerHTML = `
    <div>Showing <span class="font-bold text-white">${totalItems > 0 ? (current - 1) * pageState.pageSize + 1 : 0}</span> to <span class="font-bold text-white">${Math.min(current * pageState.pageSize, totalItems)}</span> of <span class="font-bold text-white">${totalItems}</span> records</div>
    <div class="flex items-center gap-2">
      <button ${current <= 1 ? "disabled" : ""} class="px-2.5 py-1 rounded-lg border border-brand-border bg-brand-cardSub text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-brand-border transition-all prev-page-btn">
        Previous
      </button>
      <span class="px-2 font-mono text-xs">Page ${current} of ${totalPages}</span>
      <button ${current >= totalPages ? "disabled" : ""} class="px-2.5 py-1 rounded-lg border border-brand-border bg-brand-cardSub text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-brand-border transition-all next-page-btn">
        Next
      </button>
    </div>
  `;

  const prevBtn = container.querySelector(".prev-page-btn");
  const nextBtn = container.querySelector(".next-page-btn");

  if (prevBtn) {
    prevBtn.onclick = () => {
      if (pageState.page > 1) {
        pageState.page--;
        onPageChange();
      }
    };
  }

  if (nextBtn) {
    nextBtn.onclick = () => {
      if (pageState.page < totalPages) {
        pageState.page++;
        onPageChange();
      }
    };
  }
}

// Utility: Escape HTML strings safely
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// -----------------------------------------------------------------------------
// Guaranteed Application Bootstrapper
// -----------------------------------------------------------------------------
// Expose loaders globally for console or inline triggers
window.loadOverviewData = loadOverviewData;
window.loadProducts = loadProducts;
window.loadCustomers = loadCustomers;
window.loadOrders = loadOrders;
window.loadInventoryMovements = loadInventoryMovements;
window.loadLowStockProducts = loadLowStockProducts;

function initializeShopApp() {
  console.log("[ShopManage] Bootstrapping client application...");

  // 1. Double safety: bind click listeners to all tab buttons
  document.querySelectorAll(".nav-tab-btn, [data-tab]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const tab = btn.getAttribute("data-tab");
      if (tab) {
        window.switchTab(tab);
      }
    });
  });

  // 2. Double safety: bind modal trigger buttons
  const headerBtn = document.getElementById("headerQuickOrderBtn");
  if (headerBtn) headerBtn.addEventListener("click", () => window.openCreateOrderModal());

  const addProdBtn = document.getElementById("openAddProductModalBtn");
  if (addProdBtn) addProdBtn.addEventListener("click", () => window.openProductModal());

  const addCustBtn = document.getElementById("openAddCustomerModalBtn");
  if (addCustBtn) addCustBtn.addEventListener("click", () => window.openCustomerModal());

  const addOrdBtn = document.getElementById("openCreateOrderModalBtn");
  if (addOrdBtn) addOrdBtn.addEventListener("click", () => window.openCreateOrderModal());

  const addStkBtn = document.getElementById("openStockModalBtn");
  if (addStkBtn) addStkBtn.addEventListener("click", () => window.openStockModal());

  // 3. Close modals when clicking backdrop overlay
  [
    "productModal",
    "customerModal",
    "customerHistoryModal",
    "orderModal",
    "orderStatusModal",
    "stockModal",
    "invoiceModal",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("click", (e) => {
        if (e.target === el) {
          el.classList.add("hidden");
        }
      });
    }
  });

  // 4. Close modals on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      [
        "productModal",
        "customerModal",
        "customerHistoryModal",
        "orderModal",
        "orderStatusModal",
        "stockModal",
        "invoiceModal",
      ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.add("hidden");
      });
    }
  });

  // 5. Initialize tab listeners & mobile navigation
  initSidebarMobile();
  initProductsTab();
  initCustomersTab();
  initOrdersTab();
  initInventoryTab();
  initLogout();

  // 6. Preload dropdowns and initial overview data
  loadOverviewData();
  preloadDropdownData();

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

window.initializeShopApp = initializeShopApp;

// Immediate check: if DOM is already ready or loading
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeShopApp);
} else {
  // DOM is already parsed! Run immediately!
  initializeShopApp();
}