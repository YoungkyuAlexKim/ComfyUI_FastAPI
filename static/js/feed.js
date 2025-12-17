(function () {
  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) node.setAttribute(k, String(v));
    });
    (children || []).forEach((c) => {
      if (c === null || c === undefined) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  const REACTIONS = [
    { key: "love", emoji: "❤️", label: "좋아요" },
    { key: "like", emoji: "👍", label: "좋아요(엄지)" },
    { key: "laugh", emoji: "😂", label: "웃겨요" },
    { key: "wow", emoji: "😮", label: "놀라워요" },
    { key: "fire", emoji: "🔥", label: "대박" },
  ];

  function fmtTime(ts) {
    try {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      return d.toLocaleString();
    } catch (_) {
      return "";
    }
  }

  function safeText(s, fallback = "") {
    return typeof s === "string" ? s : fallback;
  }

  async function jsonFetch(url, options) {
    const res = await fetch(url, options);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const detail = data && data.detail ? data.detail : `HTTP ${res.status}`;
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function normalizeReactions(it) {
    const base = { love: 0, like: 0, laugh: 0, wow: 0, fire: 0 };
    try {
      const r = it && typeof it.reactions === "object" && it.reactions ? it.reactions : null;
      if (r) {
        Object.keys(base).forEach((k) => {
          const v = r[k];
          base[k] = Number.isFinite(Number(v)) ? Number(v) : 0;
        });
      } else {
        // Backward fallback: existing like_count => love
        const lc = it && Number.isFinite(Number(it.like_count)) ? Number(it.like_count) : 0;
        base.love = lc;
      }
    } catch (_) {}
    const my = it && typeof it.my_reaction === "string" ? it.my_reaction : null;
    return { reactions: base, myReaction: my };
  }

  async function setReaction(postId, reactionKey) {
    return await jsonFetch(`/api/v1/feed/${encodeURIComponent(postId)}/reaction`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reaction: reactionKey }),
    });
  }

  function renderReactionBar({ postId, reactions, myReaction, onUpdated }) {
    const bar = el("div", { class: "feed-reactions" });

    REACTIONS.forEach((r) => {
      const btn = el("button", { class: "feed-reaction-btn", type: "button" }, [
        el("span", { class: "feed-reaction-emoji", text: r.emoji }),
        el("span", { class: "feed-reaction-count", text: String(reactions[r.key] || 0) }),
      ]);
      btn.setAttribute("aria-label", `${r.label} ${reactions[r.key] || 0}`);
      btn.classList.toggle("active", myReaction === r.key);
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (!postId) return;

        btn.disabled = true;
        try {
          const res = await setReaction(postId, r.key);
          const next = normalizeReactions({ reactions: res.reactions, my_reaction: res.my_reaction });
          // Update all buttons in this bar
          Array.from(bar.querySelectorAll(".feed-reaction-btn")).forEach((b) => {
            b.disabled = false;
          });
          REACTIONS.forEach((rr, idx) => {
            const b = bar.children[idx];
            if (!b) return;
            const cntEl = b.querySelector(".feed-reaction-count");
            if (cntEl) cntEl.textContent = String(next.reactions[rr.key] || 0);
            b.classList.toggle("active", next.myReaction === rr.key);
          });

          if (typeof onUpdated === "function") onUpdated(next);
        } catch (err) {
          try {
            window.alert(`반응 처리에 실패했어요: ${err && err.message ? err.message : "오류"}`);
          } catch (_) {}
        } finally {
          btn.disabled = false;
        }
      });
      bar.appendChild(btn);
    });

    return bar;
  }

  function ensureModal() {
    let ov = document.getElementById("feed-modal-overlay");
    if (ov) return ov;
    ov = el("div", { id: "feed-modal-overlay", class: "feed-modal-overlay", role: "dialog" });
    ov.innerHTML = `
      <div class="feed-modal">
        <div class="feed-modal-media">
          <img id="feed-modal-image" alt="게시물 이미지" />
        </div>
        <div class="feed-modal-side">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:10px;">
            <strong id="feed-modal-author">-</strong>
            <button class="chip-btn icon-only" id="feed-modal-close" type="button" aria-label="닫기">
              <i class="fas fa-times"></i>
            </button>
          </div>

          <div class="feed-modal-field">
            <label>워크플로우</label>
            <input id="feed-modal-workflow" type="text" readonly />
          </div>

          <div class="feed-modal-field">
            <label>게시 시간</label>
            <input id="feed-modal-time" type="text" readonly />
          </div>

          <div class="feed-modal-field" id="feed-modal-input-wrap" style="display:none;">
            <label>입력 이미지(썸네일)</label>
            <div class="feed-input-thumb">
              <img id="feed-modal-input-thumb" alt="입력 이미지" />
              <div style="display:flex; flex-direction:column; gap:6px;">
                <small style="color: var(--text-muted);">Img2Img 입력</small>
                <button class="chip-btn chip-btn--ghost" id="feed-modal-open-input" type="button">
                  <i class="fas fa-up-right-from-square"></i> 크게 보기
                </button>
              </div>
            </div>
          </div>

          <div class="feed-modal-field">
            <label>프롬프트</label>
            <textarea id="feed-modal-prompt" rows="8" readonly></textarea>
          </div>

          <div class="feed-actions">
            <button class="chip-btn" id="feed-modal-copy" type="button">
              <i class="fas fa-copy"></i> 프롬프트 복사
            </button>
            <div id="feed-modal-reactions"></div>
            <button class="chip-btn chip-btn--ghost feed-delete-btn" id="feed-modal-delete" type="button" style="display:none;">
              <i class="fas fa-trash"></i> 삭제
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(ov);
    ov.addEventListener("click", (e) => {
      if (e.target === ov) closeModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && ov.classList.contains("open")) closeModal();
    });
    ov.querySelector("#feed-modal-close").addEventListener("click", closeModal);
    return ov;
  }

  let modalState = { postId: null, inputUrl: null };
  let prevBodyOverflow = null;
  let confirmBusy = false;

  function ensureConfirmOverlay() {
    let ov = document.getElementById("feed-confirm-overlay");
    if (ov) return ov;
    ov = el("div", { id: "feed-confirm-overlay", class: "confirm-overlay", role: "dialog", "aria-hidden": "true" });
    ov.innerHTML = `
      <div class="confirm-card" style="max-width:520px;">
        <h3 class="confirm-title"><i class="fas fa-trash"></i> 삭제</h3>
        <p class="confirm-text">
          정말로 삭제하시겠습니까?
        </p>
        <div class="confirm-actions">
          <button class="btn-ghost" id="feed-confirm-cancel" type="button">취소</button>
          <button class="btn-danger" id="feed-confirm-ok" type="button">삭제</button>
        </div>
      </div>
    `;
    document.body.appendChild(ov);
    ov.addEventListener("click", (e) => {
      if (e.target === ov) closeConfirm();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && ov.classList.contains("open")) closeConfirm();
    });
    return ov;
  }

  function closeConfirm() {
    const ov = document.getElementById("feed-confirm-overlay");
    if (!ov) return;
    ov.classList.remove("open");
    ov.setAttribute("aria-hidden", "true");
    confirmBusy = false;
    try {
      const okBtn = document.getElementById("feed-confirm-ok");
      if (okBtn) okBtn.disabled = false;
    } catch (_) {}
  }

  function openConfirm(onOk) {
    const ov = ensureConfirmOverlay();
    const cancelBtn = ov.querySelector("#feed-confirm-cancel");
    const okBtn = ov.querySelector("#feed-confirm-ok");
    if (cancelBtn) cancelBtn.onclick = closeConfirm;
    if (okBtn) {
      okBtn.onclick = async () => {
        if (confirmBusy) return;
        confirmBusy = true;
        okBtn.disabled = true;
        try {
          await onOk();
          closeConfirm();
        } catch (err) {
          confirmBusy = false;
          okBtn.disabled = false;
          try {
            window.alert(`처리에 실패했어요: ${err && err.message ? err.message : "오류"}`);
          } catch (_) {}
        }
      };
    }
    ov.classList.add("open");
    ov.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    const ov = document.getElementById("feed-modal-overlay");
    if (ov) ov.classList.remove("open");

    try {
      document.body.classList.remove("feed-modal-open");
      if (prevBodyOverflow !== null) {
        document.body.style.overflow = prevBodyOverflow;
        prevBodyOverflow = null;
      } else {
        document.body.style.overflow = "";
      }
    } catch (_) {}
    modalState = { postId: null, inputUrl: null };
  }

  async function openModal(postId) {
    const ov = ensureModal();
    try {
      if (prevBodyOverflow === null) prevBodyOverflow = document.body.style.overflow || "";
      document.body.style.overflow = "hidden";
      document.body.classList.add("feed-modal-open");
    } catch (_) {}

    const img = ov.querySelector("#feed-modal-image");
    const author = ov.querySelector("#feed-modal-author");
    const wf = ov.querySelector("#feed-modal-workflow");
    const tm = ov.querySelector("#feed-modal-time");
    const prompt = ov.querySelector("#feed-modal-prompt");
    const delBtn = ov.querySelector("#feed-modal-delete");
    const copyBtn = ov.querySelector("#feed-modal-copy");
    const reactionsMount = ov.querySelector("#feed-modal-reactions");

    const inputWrap = ov.querySelector("#feed-modal-input-wrap");
    const inputThumb = ov.querySelector("#feed-modal-input-thumb");
    const openInputBtn = ov.querySelector("#feed-modal-open-input");

    const data = await jsonFetch(`/api/v1/feed/${encodeURIComponent(postId)}`);
    modalState = { postId: data.post_id, inputUrl: data.input_image_url || null };

    img.src = data.image_url || "";
    author.textContent = data.author_display || "-";
    wf.value = safeText(data.workflow_id, "");
    tm.value = fmtTime(data.published_at);
    prompt.value = safeText(data.prompt, "");

    // reactions
    try {
      if (reactionsMount) reactionsMount.innerHTML = "";
      const n = normalizeReactions(data);
      if (reactionsMount) {
        reactionsMount.appendChild(
          renderReactionBar({
            postId: data.post_id,
            reactions: n.reactions,
            myReaction: n.myReaction,
            onUpdated: (next) => {
              // also try update card bar if visible
              try {
                const card = document.querySelector(`[data-feed-post-id="${data.post_id}"]`);
                if (card) {
                  const mount = card.querySelector("[data-reaction-bar]");
                  if (mount) {
                    // re-render counts/active state without rebuilding full card
                    const btns = mount.querySelectorAll(".feed-reaction-btn");
                    REACTIONS.forEach((rr, idx) => {
                      const b = btns[idx];
                      if (!b) return;
                      const cntEl = b.querySelector(".feed-reaction-count");
                      if (cntEl) cntEl.textContent = String(next.reactions[rr.key] || 0);
                      b.classList.toggle("active", next.myReaction === rr.key);
                    });
                  }
                }
              } catch (_) {}
            },
          })
        );
      }
    } catch (_) {}

    delBtn.style.display = data.can_delete ? "" : "none";
    delBtn.onclick = async () => {
      if (!modalState.postId) return;
      openConfirm(async () => {
        await jsonFetch(`/api/v1/feed/${encodeURIComponent(modalState.postId)}/delete`, { method: "POST" });
        closeModal();
        await reload(true);
      });
    };

    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(prompt.value || "");
        copyBtn.classList.add("active");
        setTimeout(() => copyBtn.classList.remove("active"), 700);
      } catch (_) {
        try {
          window.prompt("복사할 프롬프트:", prompt.value || "");
        } catch (__) {}
      }
    };

    if (data.input_thumb_url || data.input_image_url) {
      inputWrap.style.display = "";
      inputThumb.src = data.input_thumb_url || data.input_image_url;
      openInputBtn.onclick = () => {
        if (data.input_image_url) window.open(data.input_image_url, "_blank");
      };
    } else {
      inputWrap.style.display = "none";
    }

    ov.classList.add("open");
  }

  let page = 1;
  const size = 24;
  let loading = false;
  let hasMore = true;
  let sortKey = "newest";

  function renderCard(it) {
    const card = el("div", { class: "feed-card", "data-feed-post-id": it.post_id });

    const media = el("div", { class: "feed-media" });
    const img = el("img", { class: "feed-thumb", src: it.thumb_url || it.image_url || "", alt: "게시물 이미지" });
    img.addEventListener("click", () => openModal(it.post_id));
    media.appendChild(img);

    const overlay = el("div", { class: "feed-overlay" });

    const topBadges = el("div", { class: "feed-overlay-top" });
    if (it.has_input) topBadges.appendChild(el("span", { class: "feed-badge feed-badge--input", text: "Img2Img" }));
    overlay.appendChild(topBadges);

    const metaRow = el("div", { class: "feed-overlay-meta" }, [
      el("div", { class: "feed-author", text: it.author_display || "-" }),
      el("div", { class: "feed-time", text: fmtTime(it.published_at) }),
    ]);
    overlay.appendChild(metaRow);

    const n = normalizeReactions(it);
    const reactionMount = el("div", { "data-reaction-bar": "true" });
    reactionMount.appendChild(
      renderReactionBar({
        postId: it.post_id,
        reactions: n.reactions,
        myReaction: n.myReaction,
        onUpdated: () => {},
      })
    );
    overlay.appendChild(reactionMount);

    media.appendChild(overlay);
    card.appendChild(media);
    return card;
  }

  function setLoadMoreVisible(visible) {
    const btn = document.getElementById("feed-load-more");
    if (!btn) return;
    btn.style.display = visible ? "" : "none";
  }

  async function loadPage(reset) {
    if (loading) return;
    loading = true;
    try {
      if (reset) {
        page = 1;
        hasMore = true;
      }
      const data = await jsonFetch(
        `/api/v1/feed?page=${encodeURIComponent(page)}&size=${encodeURIComponent(size)}&sort=${encodeURIComponent(sortKey)}`
      );
      const items = Array.isArray(data.items) ? data.items : [];
      const grid = document.getElementById("feed-grid");
      if (!grid) return;
      if (reset) grid.innerHTML = "";
      items.forEach((it) => grid.appendChild(renderCard(it)));
      const totalPages = data.total_pages || 1;
      hasMore = page < totalPages;
      setLoadMoreVisible(hasMore);
      if (hasMore) page += 1;
    } finally {
      loading = false;
    }
  }

  async function reload(reset) {
    return await loadPage(reset);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const btnMore = document.getElementById("feed-load-more");
    const btnRefresh = document.getElementById("feed-refresh");
    const sortSel = document.getElementById("feed-sort");
    if (btnMore) btnMore.addEventListener("click", () => loadPage(false));
    if (btnRefresh) btnRefresh.addEventListener("click", () => loadPage(true));

    try {
      const saved = localStorage.getItem("feedSortKey") || "";
      if (saved) sortKey = saved;
      if (sortSel) sortSel.value = sortKey;
    } catch (_) {}

    if (sortSel) {
      sortSel.addEventListener("change", () => {
        try {
          sortKey = sortSel.value || "newest";
          localStorage.setItem("feedSortKey", sortKey);
        } catch (_) {
          sortKey = sortSel.value || "newest";
        }
        loadPage(true);
      });
    }
    loadPage(true);
  });
})();


