import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from aiohttp import web
from aiohttp.web import Request, Response, json_response

from config import WEB_HOST, WEB_PORT, WEB_BASE_URL, SESSIONS_DIR
from database.db import get_order_link_by_token, mark_order_link_accessed
from database.models import Account, AccountStatus
from services.session_manager import (
    get_session_file_path,
    get_account_dialogs,
    get_chat_paged_messages,
    send_message_as_account,
    click_bot_message_button,
    download_message_photo_bytes,
    get_latest_login_code
)

logger = logging.getLogger("web_app")

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Telegram Web Client</title>
    <style>
        :root {
            --bg-primary: #0e1621;
            --bg-secondary: #17212b;
            --bg-hover: #202b36;
            --bg-active: #2b5278;
            --msg-in: #182533;
            --msg-out: #2b5278;
            --text-primary: #f5f5f5;
            --text-secondary: #7f91a4;
            --text-muted: #5e6d7d;
            --accent: #5288c1;
            --accent-hover: #6499d3;
            --border: #131c26;
            --badge: #5288c1;
            --btn-bg: #242f3d;
            --btn-hover: #2c3847;
            --code-bg: #1c2733;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: var(--bg-primary);
            color: var(--text-primary);
            height: 100vh;
            overflow: hidden;
            display: flex;
        }

        #app {
            display: flex;
            width: 100vw;
            height: 100vh;
            position: relative;
        }

        /* Sidebar / Dialogs */
        .sidebar {
            width: 380px;
            min-width: 300px;
            height: 100%;
            background-color: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            z-index: 10;
            transition: transform 0.25s ease;
        }

        .sidebar-header {
            padding: 12px 16px;
            background-color: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .account-badge {
            display: flex;
            align-items: center;
            gap: 10px;
            overflow: hidden;
        }

        .avatar {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: linear-gradient(135deg, #5288c1, #366394);
            color: #fff;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 16px;
            flex-shrink: 0;
            text-transform: uppercase;
        }

        .account-meta {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .account-name {
            font-weight: 600;
            font-size: 14px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .account-phone {
            font-size: 12px;
            color: var(--accent);
            font-family: monospace;
        }

        .search-box {
            padding: 8px 16px;
            background-color: var(--bg-secondary);
        }

        .search-input {
            width: 100%;
            padding: 8px 12px;
            background-color: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 20px;
            color: var(--text-primary);
            font-size: 13px;
            outline: none;
        }
        .search-input:focus {
            border-color: var(--accent);
        }

        .filter-tabs {
            display: flex;
            gap: 6px;
            padding: 6px 12px 10px;
            overflow-x: auto;
            border-bottom: 1px solid var(--border);
        }
        .filter-tabs::-webkit-scrollbar {
            display: none;
        }

        .filter-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 12px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
        }
        .filter-btn.active, .filter-btn:hover {
            background-color: var(--bg-hover);
            color: var(--text-primary);
        }
        .filter-btn.active {
            background-color: var(--accent);
            color: #fff;
        }

        .dialogs-list {
            flex: 1;
            overflow-y: auto;
        }
        .dialogs-list::-webkit-scrollbar {
            width: 5px;
        }
        .dialogs-list::-webkit-scrollbar-thumb {
            background: var(--bg-hover);
            border-radius: 4px;
        }

        .dialog-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 16px;
            cursor: pointer;
            border-bottom: 1px solid rgba(255,255,255,0.02);
            transition: background-color 0.15s;
        }
        .dialog-item:hover {
            background-color: var(--bg-hover);
        }
        .dialog-item.active {
            background-color: var(--bg-active);
        }

        .dialog-content {
            flex: 1;
            min-width: 0;
        }

        .dialog-top {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 4px;
        }

        .dialog-title {
            font-size: 14px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .dialog-time {
            font-size: 11px;
            color: var(--text-muted);
            margin-left: 6px;
            flex-shrink: 0;
        }

        .dialog-bottom {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .dialog-snippet {
            font-size: 13px;
            color: var(--text-secondary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .badge {
            background-color: var(--badge);
            color: white;
            font-size: 11px;
            font-weight: bold;
            padding: 2px 7px;
            border-radius: 10px;
            margin-left: 6px;
            flex-shrink: 0;
        }

        /* Chat Area */
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            background-color: var(--bg-primary);
            position: relative;
        }

        .chat-header {
            padding: 10px 18px;
            background-color: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            z-index: 5;
        }

        .chat-header-info {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .chat-header-title {
            font-size: 15px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .chat-header-status {
            font-size: 12px;
            color: var(--text-secondary);
        }

        .chat-header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .header-btn {
            background-color: var(--btn-bg);
            color: var(--text-primary);
            border: 1px solid var(--border);
            padding: 6px 12px;
            border-radius: 16px;
            font-size: 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: background-color 0.2s;
        }
        .header-btn:hover {
            background-color: var(--btn-hover);
        }
        .header-btn.accent {
            background-color: var(--accent);
            border-color: var(--accent);
        }

        .back-btn {
            display: none;
            background: none;
            border: none;
            color: var(--text-primary);
            font-size: 20px;
            cursor: pointer;
            margin-right: 8px;
        }

        /* Code Notification Bar */
        .otp-bar {
            background: linear-gradient(90deg, #1d334a, #203f5f);
            border-bottom: 1px solid var(--accent);
            padding: 8px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
        }
        .otp-code {
            font-family: monospace;
            font-weight: bold;
            font-size: 16px;
            color: #4ade80;
            background: rgba(0,0,0,0.3);
            padding: 2px 8px;
            border-radius: 4px;
            letter-spacing: 2px;
            cursor: pointer;
        }

        /* Messages Container */
        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 16px 24px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .messages-container::-webkit-scrollbar {
            width: 6px;
        }
        .messages-container::-webkit-scrollbar-thumb {
            background: var(--bg-hover);
            border-radius: 4px;
        }

        .message-bubble {
            max-width: 70%;
            padding: 8px 12px 6px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.4;
            position: relative;
            word-break: break-word;
            display: flex;
            flex-direction: column;
        }

        .message-bubble.incoming {
            align-self: flex-start;
            background-color: var(--msg-in);
            border-bottom-left-radius: 4px;
        }

        .message-bubble.outgoing {
            align-self: flex-end;
            background-color: var(--msg-out);
            border-bottom-right-radius: 4px;
        }

        .message-sender {
            font-size: 12px;
            font-weight: 600;
            color: var(--accent);
            margin-bottom: 3px;
        }

        .message-text {
            white-space: pre-wrap;
        }

        .message-meta {
            align-self: flex-end;
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 4px;
            margin-left: 8px;
        }

        .message-photo {
            max-width: 100%;
            border-radius: 8px;
            margin-bottom: 6px;
            cursor: pointer;
            display: block;
        }

        /* Inline Keyboard Buttons under message */
        .inline-keyboard {
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-top: 8px;
        }
        .inline-row {
            display: flex;
            gap: 4px;
        }
        .inline-btn {
            flex: 1;
            background-color: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.12);
            color: #fff;
            padding: 7px 10px;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: background-color 0.15s;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .inline-btn:hover {
            background-color: rgba(255,255,255,0.18);
        }

        /* Reply Keyboard at bottom */
        .reply-keyboard {
            background-color: var(--bg-secondary);
            border-top: 1px solid var(--border);
            padding: 8px 16px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .reply-row {
            display: flex;
            gap: 6px;
        }
        .reply-btn {
            flex: 1;
            background-color: var(--btn-bg);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            text-align: center;
            transition: background-color 0.15s;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .reply-btn:hover {
            background-color: var(--btn-hover);
        }

        /* Composer */
        .composer {
            padding: 10px 16px;
            background-color: var(--bg-secondary);
            border-top: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .composer-input {
            flex: 1;
            padding: 10px 16px;
            background-color: var(--bg-primary);
            border: 1px solid var(--border);
            border-radius: 22px;
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
            resize: none;
            max-height: 100px;
        }
        .composer-input:focus {
            border-color: var(--accent);
        }

        .send-btn {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            background-color: var(--accent);
            color: white;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
            transition: transform 0.15s, background-color 0.2s;
        }
        .send-btn:hover {
            background-color: var(--accent-hover);
            transform: scale(1.05);
        }
        .send-btn svg {
            width: 18px;
            height: 18px;
            fill: currentColor;
        }

        /* Empty state */
        .empty-state {
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: var(--text-secondary);
            gap: 12px;
        }

        /* Modal image preview */
        .modal {
            display: none;
            position: fixed;
            z-index: 100;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.85);
            align-items: center;
            justify-content: center;
        }
        .modal.active {
            display: flex;
        }
        .modal img {
            max-width: 90%;
            max-height: 90%;
            border-radius: 8px;
        }

        /* Mobile Responsive */
        @media (max-width: 768px) {
            .sidebar {
                width: 100vw;
                position: absolute;
                left: 0;
                top: 0;
            }
            .sidebar.hidden {
                transform: translateX(-100%);
            }
            .chat-area {
                width: 100vw;
            }
            .back-btn {
                display: block;
            }
            .message-bubble {
                max-width: 85%;
            }
        }
    </style>
</head>
<body>
    <div id="app">
        <!-- Sidebar -->
        <div class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <div class="account-badge">
                    <div class="avatar" id="acc-avatar">TG</div>
                    <div class="account-meta">
                        <span class="account-name" id="acc-name">Загрузка...</span>
                        <span class="account-phone" id="acc-phone">+...</span>
                    </div>
                </div>
                <button class="header-btn" onclick="fetchAuthCode()" title="Получить свежий код от Telegram">🔑 Код</button>
            </div>

            <div class="search-box">
                <input type="text" class="search-input" id="search-input" placeholder="🔍 Поиск диалогов..." oninput="handleSearch(this.value)">
            </div>

            <div class="filter-tabs">
                <button class="filter-btn active" onclick="setFilter('all', this)">Все</button>
                <button class="filter-btn" onclick="setFilter('user', this)">👤 ЛС</button>
                <button class="filter-btn" onclick="setFilter('bot', this)">🤖 Боты</button>
                <button class="filter-btn" onclick="setFilter('group', this)">👥 Группы</button>
                <button class="filter-btn" onclick="setFilter('channel', this)">📢 Каналы</button>
            </div>

            <div class="dialogs-list" id="dialogs-list">
                <div style="padding: 20px; text-align: center; color: var(--text-secondary);">
                    ⏳ Загрузка диалогов...
                </div>
            </div>
        </div>

        <!-- Chat Area -->
        <div class="chat-area" id="chat-area">
            <!-- OTP Bar -->
            <div class="otp-bar" id="otp-bar" style="display: none;">
                <span>📩 Свежий код подтверждения:</span>
                <span class="otp-code" id="otp-code-val" onclick="copyOtp()" title="Нажмите для копирования">12345</span>
                <button class="header-btn" onclick="document.getElementById('otp-bar').style.display='none'">✕</button>
            </div>

            <!-- Chat Header -->
            <div class="chat-header" id="chat-header" style="display: none;">
                <div class="chat-header-info">
                    <button class="back-btn" onclick="showSidebar()">‹</button>
                    <div class="avatar" id="chat-avatar" style="width:36px; height:36px; font-size:14px;">💬</div>
                    <div>
                        <div class="chat-header-title" id="chat-title">Чат</div>
                        <div class="chat-header-status" id="chat-status">активен</div>
                    </div>
                </div>
                <div class="chat-header-actions">
                    <button class="header-btn" onclick="refreshCurrentChat()" title="Обновить сообщения">🔄</button>
                </div>
            </div>

            <!-- Messages Area -->
            <div class="messages-container" id="messages-container">
                <div class="empty-state" id="empty-state">
                    <div style="font-size: 48px;">💬</div>
                    <h3>Выберите чат для начала общения</h3>
                    <p>Все сообщения синхронизируются с Telegram в реальном времени</p>
                </div>
            </div>

            <!-- Reply Keyboard -->
            <div class="reply-keyboard" id="reply-keyboard" style="display: none;"></div>

            <!-- Composer -->
            <div class="composer" id="composer" style="display: none;">
                <input type="text" class="composer-input" id="composer-input" placeholder="Написать сообщение..." onkeydown="if(event.key==='Enter') sendMessage()">
                <button class="send-btn" onclick="sendMessage()" title="Отправить">
                    <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
                </button>
            </div>
        </div>
    </div>

    <!-- Image Modal -->
    <div class="modal" id="image-modal" onclick="this.classList.remove('active')">
        <img id="modal-img" src="" alt="Preview">
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token') || '';
        let currentChatId = null;
        let currentFilter = 'all';
        let allDialogs = [];
        let refreshInterval = null;

        async function init() {
            if (!token) {
                document.body.innerHTML = '<div style="color:white; padding:40px; text-align:center;"><h2>❌ Ошибка доступа</h2><p>Токен авторизации не указан в ссылке.</p></div>';
                return;
            }
            // Execute parallel fetches for instantaneous loading
            Promise.all([fetchAccountInfo(), fetchDialogs(), fetchAuthCode()]);
        }

        async function fetchAccountInfo() {
            try {
                const res = await fetch(`/api/account_info?token=${token}`);
                const data = await res.json();
                if (data.ok) {
                    document.getElementById('acc-name').innerText = data.name || 'Аккаунт';
                    document.getElementById('acc-phone').innerText = data.phone || '';
                    document.getElementById('acc-avatar').innerText = (data.name || data.phone || 'TG').slice(0,2).toUpperCase();
                } else {
                    document.body.innerHTML = `<div style="color:white; padding:40px; text-align:center;"><h2>❌ Ссылка недействительна</h2><p>${data.error || 'Срок действия ссылки истек.'}</p></div>`;
                }
            } catch(e) {
                console.error(e);
            }
        }

        async function fetchAuthCode() {
            try {
                const res = await fetch(`/api/auth_code?token=${token}`);
                const data = await res.json();
                if (data.ok && data.code) {
                    document.getElementById('otp-code-val').innerText = data.code;
                    document.getElementById('otp-bar').style.display = 'flex';
                }
            } catch(e) {}
        }

        function copyOtp() {
            const code = document.getElementById('otp-code-val').innerText;
            navigator.clipboard.writeText(code);
            alert(`Код ${code} скопирован в буфер обмена!`);
        }

        async function fetchDialogs() {
            try {
                const res = await fetch(`/api/dialogs?token=${token}`);
                const data = await res.json();
                if (data.ok) {
                    allDialogs = data.dialogs || [];
                    renderDialogs();
                } else {
                    document.getElementById('dialogs-list').innerHTML = `<div style="padding:20px; color:#ef4444; text-align:center;">${data.error || 'Ошибка загрузки диалогов'}</div>`;
                }
            } catch(e) {
                document.getElementById('dialogs-list').innerHTML = '<div style="padding:20px; color:#ef4444; text-align:center;">Ошибка подключения к серверу</div>';
            }
        }

        function renderDialogs() {
            const listEl = document.getElementById('dialogs-list');
            const searchVal = (document.getElementById('search-input').value || '').toLowerCase();
            
            const filtered = allDialogs.filter(d => {
                if (currentFilter !== 'all' && d.type !== currentFilter) return false;
                if (searchVal && !(d.title || '').toLowerCase().includes(searchVal)) return false;
                return true;
            });

            if (filtered.length === 0) {
                listEl.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-secondary);">Нет диалогов в этой категории</div>';
                return;
            }

            listEl.innerHTML = filtered.map(d => {
                const isActive = d.id === currentChatId ? 'active' : '';
                const initial = (d.title || '💬').slice(0, 1).toUpperCase();
                const unreadBadge = d.unread_count > 0 ? `<span class="badge">${d.unread_count}</span>` : '';
                const dateStr = d.date ? d.date.split(' ')[0] : '';
                
                return `
                    <div class="dialog-item ${isActive}" onclick="selectChat(${d.id}, '${escapeHtml(d.title)}')">
                        <div class="avatar" style="width:42px; height:42px; font-size:16px;">${initial}</div>
                        <div class="dialog-content">
                            <div class="dialog-top">
                                <span class="dialog-title">${escapeHtml(d.title)}</span>
                                <span class="dialog-time">${dateStr}</span>
                            </div>
                            <div class="dialog-bottom">
                                <span class="dialog-snippet">${escapeHtml(d.last_message || '')}</span>
                                ${unreadBadge}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function setFilter(filter, btn) {
            currentFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderDialogs();
        }

        function handleSearch() {
            renderDialogs();
        }

        async function selectChat(chatId, title) {
            currentChatId = chatId;
            renderDialogs();

            // Switch to chat view on mobile
            if (window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.add('hidden');
            }

            document.getElementById('chat-header').style.display = 'flex';
            document.getElementById('composer').style.display = 'flex';
            document.getElementById('chat-title').innerText = title;
            document.getElementById('chat-avatar').innerText = (title || '💬').slice(0,1).toUpperCase();

            await loadMessages(chatId);

            // Set up polling for active chat
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(() => {
                if (currentChatId === chatId) {
                    loadMessages(chatId, true);
                }
            }, 3000);
        }

        async function loadMessages(chatId, isSilent = false) {
            const container = document.getElementById('messages-container');
            if (!isSilent) {
                container.innerHTML = '<div style="margin:auto; color:var(--text-secondary);">⏳ Загрузка сообщений...</div>';
            }

            try {
                const res = await fetch(`/api/messages?token=${token}&chat_id=${chatId}`);
                const data = await res.json();
                if (data.ok) {
                    renderMessages(data.messages || []);
                    renderReplyKeyboard(data.reply_keyboard || []);
                } else {
                    if (!isSilent) container.innerHTML = `<div style="margin:auto; color:#ef4444;">${data.error || 'Ошибка загрузки сообщений'}</div>`;
                }
            } catch(e) {
                if (!isSilent) container.innerHTML = '<div style="margin:auto; color:#ef4444;">Ошибка соединения</div>';
            }
        }

        function renderMessages(messages) {
            const container = document.getElementById('messages-container');
            if (messages.length === 0) {
                container.innerHTML = '<div style="margin:auto; color:var(--text-secondary);">В этом чате пока нет сообщений</div>';
                return;
            }

            const html = messages.map(m => {
                const bubbleType = m.is_out ? 'outgoing' : 'incoming';
                const senderName = (!m.is_out && m.sender) ? `<div class="message-sender">${escapeHtml(m.sender)}</div>` : '';
                
                let photoHtml = '';
                if (m.has_photo) {
                    photoHtml = `<img class="message-photo" src="/api/photo?token=${token}&chat_id=${currentChatId}&msg_id=${m.id}" onclick="previewImage(this.src)">`;
                }

                // Render inline buttons if present
                let buttonsHtml = '';
                if (m.buttons && m.buttons.length > 0) {
                    buttonsHtml = '<div class="inline-keyboard">' + m.buttons.map(row => {
                        return '<div class="inline-row">' + row.map(b => {
                            if (b.is_url && b.url) {
                                return `<a href="${b.url}" target="_blank" class="inline-btn">🔗 ${escapeHtml(b.text)}</a>`;
                            } else {
                                return `<button class="inline-btn" onclick="clickButton(${m.id}, '${b.row}_${b.col}')">🔘 ${escapeHtml(b.text)}</button>`;
                            }
                        }).join('') + '</div>';
                    }).join('') + '</div>';
                }

                return `
                    <div class="message-bubble ${bubbleType}">
                        ${senderName}
                        ${photoHtml}
                        <div class="message-text">${formatMessageText(m.text || '')}</div>
                        ${buttonsHtml}
                        <div class="message-meta">${m.date || ''}</div>
                    </div>
                `;
            }).join('');

            const shouldScroll = container.scrollTop + container.clientHeight >= container.scrollHeight - 100 || container.scrollTop === 0;
            container.innerHTML = html;
            if (shouldScroll) {
                container.scrollTop = container.scrollHeight;
            }
        }

        function renderReplyKeyboard(rows) {
            const el = document.getElementById('reply-keyboard');
            if (!rows || rows.length === 0) {
                el.style.display = 'none';
                return;
            }
            el.style.display = 'flex';
            el.innerHTML = rows.map(row => {
                return '<div class="reply-row">' + row.map(btnText => {
                    return `<button class="reply-btn" onclick="sendReplyButton('${escapeHtml(btnText)}')">⌨️ ${escapeHtml(btnText)}</button>`;
                }).join('') + '</div>';
            }).join('');
        }

        async function sendMessage() {
            const input = document.getElementById('composer-input');
            const text = input.value.trim();
            if (!text || !currentChatId) return;

            input.value = '';
            try {
                const res = await fetch('/api/send_message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ token: token, chat_id: currentChatId, text: text })
                });
                const data = await res.json();
                if (data.ok) {
                    loadMessages(currentChatId, true);
                    fetchDialogs();
                } else {
                    alert(data.error || 'Не удалось отправить сообщение');
                }
            } catch(e) {
                alert('Ошибка сети при отправке');
            }
        }

        async function sendReplyButton(btnText) {
            if (!currentChatId) return;
            try {
                await fetch('/api/send_message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ token: token, chat_id: currentChatId, text: btnText })
                });
                loadMessages(currentChatId, true);
                fetchDialogs();
            } catch(e) {}
        }

        async function clickButton(msgId, dataStr) {
            if (!currentChatId) return;
            try {
                const res = await fetch('/api/click_button', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ token: token, chat_id: currentChatId, msg_id: msgId, data: dataStr })
                });
                const data = await res.json();
                setTimeout(() => loadMessages(currentChatId, true), 500);
            } catch(e) {}
        }

        function refreshCurrentChat() {
            if (currentChatId) {
                loadMessages(currentChatId);
                fetchDialogs();
                fetchAuthCode();
            }
        }

        function showSidebar() {
            document.getElementById('sidebar').classList.remove('hidden');
        }

        function previewImage(src) {
            document.getElementById('modal-img').src = src;
            document.getElementById('image-modal').classList.add('active');
        }

        function escapeHtml(str) {
            return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
        }

        function formatMessageText(text) {
            let escaped = escapeHtml(text);
            const urlRegex = /(https?:\/\/[^\s]+)/g;
            return escaped.replace(urlRegex, url => `<a href="${url}" target="_blank" style="color:var(--accent);">${url}</a>`);
        }

        window.onload = init;
    </script>
</body>
</html>"""

# --- HTTP Route Handlers ---

async def handle_index(request: Request) -> Response:
    token = request.query.get("token", "")
    if token:
        raise web.HTTPFound(location=f"/web?token={token}")
    return Response(text="<h1>Telegram Web Client Server Active</h1>", content_type="text/html")


async def handle_web_page(request: Request) -> Response:
    return Response(text=HTML_TEMPLATE, content_type="text/html")


async def _get_account_from_request(request: Request) -> Tuple[Optional[Account], Optional[str]]:
    token = request.query.get("token") or ""
    if not token and request.can_read_body:
        try:
            body = await request.json()
            token = body.get("token", "")
        except Exception:
            pass

    if not token:
        return None, "Токен не передан"

    order = await get_order_link_by_token(token)
    if not order or not order.account:
        return None, "Неверный или просроченный токен"

    if not order.is_active:
        return None, "Ссылка деактивирована"

    return order.account, None


async def handle_api_account_info(request: Request) -> Response:
    acc, err = await _get_account_from_request(request)
    if not acc:
        return json_response({"ok": False, "error": err})

    return json_response({
        "ok": True,
        "phone": acc.phone,
        "name": acc.full_name(),
        "first_name": acc.first_name,
        "last_name": acc.last_name,
        "username": acc.username,
        "two_fa": acc.two_fa
    })


async def handle_api_dialogs(request: Request) -> Response:
    acc, err = await _get_account_from_request(request)
    if not acc:
        return json_response({"ok": False, "error": err})

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, dialogs, msg = await get_account_dialogs(session_file, proxy=proxy_dict, limit=35)
    if not ok:
        return json_response({"ok": False, "error": msg})

    return json_response({
        "ok": True,
        "phone": acc.phone,
        "name": acc.full_name(),
        "dialogs": dialogs
    })


async def handle_api_messages(request: Request) -> Response:
    acc, err = await _get_account_from_request(request)
    if not acc:
        return json_response({"ok": False, "error": err})

    chat_id_str = request.query.get("chat_id")
    if not chat_id_str:
        return json_response({"ok": False, "error": "chat_id обязателен"})

    try:
        chat_id = int(chat_id_str)
    except ValueError:
        return json_response({"ok": False, "error": "Неверный chat_id"})

    offset_id = int(request.query.get("offset_id", 0))
    limit = int(request.query.get("limit", 25))

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, chat_info, messages, oldest_id, msg = await get_chat_paged_messages(
        session_file,
        chat_id=chat_id,
        offset_id=offset_id,
        limit=limit,
        proxy=proxy_dict
    )

    if not ok:
        return json_response({"ok": False, "error": msg})

    return json_response({
        "ok": True,
        "chat_info": chat_info,
        "messages": messages,
        "oldest_msg_id": oldest_id,
        "reply_keyboard": chat_info.get("reply_keyboard", [])
    })


async def handle_api_send_message(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "Неверный JSON"})

    token = body.get("token")
    chat_id = body.get("chat_id")
    text = body.get("text", "").strip()

    if not token or not chat_id or not text:
        return json_response({"ok": False, "error": "Все поля (token, chat_id, text) обязательны"})

    order = await get_order_link_by_token(token)
    if not order or not order.account:
        return json_response({"ok": False, "error": "Токен не найден"})

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, msg = await send_message_as_account(session_file, chat_id=int(chat_id), text=text, proxy=proxy_dict)
    return json_response({"ok": ok, "result": msg})


async def handle_api_click_button(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception:
        return json_response({"ok": False, "error": "Неверный JSON"})

    token = body.get("token")
    chat_id = body.get("chat_id")
    msg_id = body.get("msg_id")
    data = body.get("data")

    if not token or not chat_id or not msg_id or not data:
        return json_response({"ok": False, "error": "Недостаточно данных"})

    order = await get_order_link_by_token(token)
    if not order or not order.account:
        return json_response({"ok": False, "error": "Токен не найден"})

    acc = order.account
    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, res = await click_bot_message_button(
        session_file,
        chat_id=int(chat_id),
        message_id=int(msg_id),
        button_data=data,
        proxy=proxy_dict
    )
    return json_response({"ok": ok, "result": res})


async def handle_api_photo(request: Request) -> Response:
    acc, err = await _get_account_from_request(request)
    if not acc:
        return Response(status=403, text=err or "Forbidden")

    chat_id = int(request.query.get("chat_id", 0))
    msg_id = int(request.query.get("msg_id", 0))

    if not chat_id or not msg_id:
        return Response(status=400, text="chat_id and msg_id required")

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    ok, photo_bytes, _, err_msg = await download_message_photo_bytes(session_file, chat_id, msg_id, proxy=proxy_dict)
    if not ok or not photo_bytes:
        return Response(status=404, text=err_msg or "Image not found")

    return Response(body=photo_bytes, content_type="image/jpeg")


async def handle_api_auth_code(request: Request) -> Response:
    acc, err = await _get_account_from_request(request)
    if not acc:
        return json_response({"ok": False, "error": err})

    session_file = get_session_file_path(acc.session_name)
    proxy_dict = acc.proxy.to_telethon_dict() if acc.proxy else None

    code, details, raw = await get_latest_login_code(session_file, proxy=proxy_dict, max_age_seconds=1800)
    return json_response({
        "ok": bool(code),
        "code": code,
        "details": details,
        "raw": raw
    })


def create_web_application() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/web", handle_web_page)
    app.router.add_get("/api/account_info", handle_api_account_info)
    app.router.add_get("/api/dialogs", handle_api_dialogs)
    app.router.add_get("/api/messages", handle_api_messages)
    app.router.add_post("/api/send_message", handle_api_send_message)
    app.router.add_post("/api/click_button", handle_api_click_button)
    app.router.add_get("/api/photo", handle_api_photo)
    app.router.add_get("/api/auth_code", handle_api_auth_code)
    return app


async def start_web_server(host: str = WEB_HOST, port: int = WEB_PORT) -> web.AppRunner:
    app = create_web_application()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"🌐 Web Client запущен на http://{host}:{port}/ (Внешний URL: {WEB_BASE_URL})")
    return runner
