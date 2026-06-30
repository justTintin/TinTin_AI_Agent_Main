const { ipcRenderer } = require('electron');

// 仅在最外层主框架中执行，忽略子 iframe，防止子 frame 销毁时引起的 WebFrameMain 销毁竞争导致的崩溃
if (window.self !== window.top) {
  return;
}

// 1. Inject script into the page's execution context (Main World) to monkeypatch fetch/XHR/MSE
function injectMainWorldScript() {
  const scriptContent = `
    (function() {
      // Keep track of MediaSource blob URLs
      const mediaSourceToBlobUrl = new Map();
      const originalCreateObjectURL = URL.createObjectURL;
      URL.createObjectURL = function(obj) {
        const url = originalCreateObjectURL.call(this, obj);
        if (obj instanceof MediaSource) {
          mediaSourceToBlobUrl.set(obj, url);
        }
        return url;
      };

      // Keep track of SourceBuffer mime types and MediaSource reference
      const originalAddSourceBuffer = MediaSource.prototype.addSourceBuffer;
      MediaSource.prototype.addSourceBuffer = function(mime) {
        const sb = originalAddSourceBuffer.call(this, mime);
        sb._mime = mime;
        sb._mediaSource = this;
        return sb;
      };

      // Intercept appendBuffer to match segment URLs to video elements
      const originalAppendBuffer = SourceBuffer.prototype.appendBuffer;
      SourceBuffer.prototype.appendBuffer = function(buf) {
        try {
          // 兼容处理：buf 可能是 Uint8Array 等 TypedArray 视图，其 _url 属性保存在底层的 ArrayBuffer 上 (buf.buffer._url)
          const url = buf ? (buf._url || (buf.buffer && buf.buffer._url)) : null;
          if (url) {
            const mime = this._mime || '';
            const type = mime.toLowerCase().includes('audio') ? 'audio' : 'video';
            const mediaSource = this._mediaSource;
            const blobUrl = mediaSourceToBlobUrl.get(mediaSource);
            if (blobUrl) {
              window.postMessage({
                source: 'tintin-sniffer',
                type: 'mse-segment-appended',
                data: { url, type, blobUrl }
              }, '*');
            }
          }
        } catch (e) {
          console.error('Error in appendBuffer interceptor:', e);
        }
        return originalAppendBuffer.call(this, buf);
      };

      // Helper to check if a URL is a media resource
      function isMediaUrl(url) {
        if (!url || typeof url !== 'string') return false;
        // Ignore data urls
        if (url.startsWith('data:')) return false;
        
        const lower = url.toLowerCase();
        
        // Match common video/audio/image extensions
        if (lower.includes('.mp4') || lower.includes('.m3u8') || lower.includes('.mp3') || 
            lower.includes('.flv') || lower.includes('.webm') || lower.includes('.ogg') ||
            lower.includes('.m4s') || lower.includes('.ts')) {
          return true;
        }
        
        // Match specific API video streams or image CDN formats
        if (lower.includes('video/tos') || lower.includes('sns-video') || 
            lower.includes('sns-img') || lower.includes('sns-webpic') ||
            lower.includes('v-code') || lower.includes('upos-sz-mirrstar') ||
            lower.includes('videoplayback') || lower.includes('.douyinvod.com')) {
          return true;
        }
        
        return false;
      }

      function getMediaTypeFromUrl(url) {
        const lower = url.toLowerCase();
        if (lower.includes('.mp3') || lower.includes('mime=audio') || lower.includes('media-audio') || 
            lower.includes('-30216') || lower.includes('-30232') || lower.includes('-30280') || 
            lower.includes('-30250') || lower.includes('audio')) {
          return 'audio';
        }
        return 'video';
      }

      function sendMediaNotification(url, type = 'video') {
        window.postMessage({ source: 'tintin-sniffer', type: 'media-detected', data: { url, type } }, '*');
      }

      // Monkeypatch fetch
      const originalFetch = window.fetch;
      window.fetch = async function(...args) {
        const url = args[0];
        const resPromise = originalFetch.apply(this, args);
        
        let urlStr = '';
        if (typeof url === 'string') {
          urlStr = url;
        } else if (url && url.url) {
          urlStr = url.url;
        }
        
        if (isMediaUrl(urlStr)) {
          sendMediaNotification(urlStr, getMediaTypeFromUrl(urlStr));
        }
        
        // Also intercept API responses for follower syncing
        try {
          const response = await resPromise;
          response._url = urlStr;
          const clone = response.clone();
          
          if (urlStr.includes('api') || urlStr.includes('following') || urlStr.includes('subscribe') || urlStr.includes('relation') || urlStr.includes('aweme/v1/web/aweme/post') || urlStr.includes('members') || urlStr.includes('activities') || urlStr.includes('user_posted') || urlStr.includes('collect') || urlStr.includes('fav') || urlStr.includes('youtubei') || urlStr.includes('item_list') || urlStr.includes('hot/search') || urlStr.includes('hot-lists') || urlStr.includes('ranking') || urlStr.includes('search/hot')) {
            clone.json().then(data => {
              window.postMessage({ source: 'tintin-sniffer', type: 'api-response', data: { url: urlStr, payload: data } }, '*');
            }).catch(() => {});
          }
          return response;
        } catch(e) {
          return resPromise;
        }
      };

      // Monkeypatch Response.prototype.arrayBuffer
      const originalResponseArrayBuffer = Response.prototype.arrayBuffer;
      Response.prototype.arrayBuffer = async function() {
        const buf = await originalResponseArrayBuffer.call(this);
        if (buf && this._url) {
          buf._url = this._url;
        }
        return buf;
      };

      // Also override Response.prototype.clone to pass down the URL
      const originalResponseClone = Response.prototype.clone;
      Response.prototype.clone = function() {
        const cloned = originalResponseClone.call(this);
        cloned._url = this._url;
        return cloned;
      };

      // Monkeypatch Response.prototype.blob to tag Blob
      const originalResponseBlob = Response.prototype.blob;
      Response.prototype.blob = async function() {
        const b = await originalResponseBlob.call(this);
        if (b && this._url) {
          b._url = this._url;
        }
        return b;
      };

      // Monkeypatch XMLHttpRequest
      const originalOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function(method, url, ...args) {
        this._url = url;
        return originalOpen.apply(this, [method, url, ...args]);
      };

      const originalSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', () => {
          const urlStr = this._url;
          if (isMediaUrl(urlStr)) {
            sendMediaNotification(urlStr, getMediaTypeFromUrl(urlStr));
          }
          
          // API responses
          if (urlStr.includes('api') || urlStr.includes('following') || urlStr.includes('subscribe') || urlStr.includes('relation') || urlStr.includes('aweme/v1/web/aweme/post') || urlStr.includes('members') || urlStr.includes('activities') || urlStr.includes('user_posted') || urlStr.includes('collect') || urlStr.includes('fav') || urlStr.includes('youtubei') || urlStr.includes('item_list') || urlStr.includes('hot/search') || urlStr.includes('hot-lists') || urlStr.includes('ranking') || urlStr.includes('search/hot')) {
            try {
              const data = JSON.parse(this.responseText);
              window.postMessage({ source: 'tintin-sniffer', type: 'api-response', data: { url: urlStr, payload: data } }, '*');
            } catch(e){}
          }
        });
        return originalSend.apply(this, args);
      };

      // Override response getter of XHR to tag ArrayBuffer
      const responseProp = Object.getOwnPropertyDescriptor(XMLHttpRequest.prototype, 'response');
      if (responseProp && responseProp.get) {
        const originalResponseGet = responseProp.get;
        Object.defineProperty(XMLHttpRequest.prototype, 'response', {
          get: function() {
            const res = originalResponseGet.call(this);
            if (res && res instanceof ArrayBuffer && this._url) {
              res._url = this._url;
            }
            return res;
          },
          configurable: true,
          enumerable: true
        });
      }

      // Monkeypatch Blob.prototype.arrayBuffer
      const originalBlobArrayBuffer = Blob.prototype.arrayBuffer;
      Blob.prototype.arrayBuffer = async function() {
        const buf = await originalBlobArrayBuffer.call(this);
        if (buf && this._url) {
          buf._url = this._url;
        }
        return buf;
      };

      // Monkeypatch FileReader.prototype.readAsArrayBuffer
      const originalFileReaderReadAsArrayBuffer = FileReader.prototype.readAsArrayBuffer;
      FileReader.prototype.readAsArrayBuffer = function(blob, ...args) {
        if (blob && blob._url) {
          this._url = blob._url;
        }
        return originalFileReaderReadAsArrayBuffer.apply(this, [blob, ...args]);
      };

      // Tag FileReader onload array buffer
      const resultProp = Object.getOwnPropertyDescriptor(FileReader.prototype, 'result');
      if (resultProp && resultProp.get) {
        const originalResultGet = resultProp.get;
        Object.defineProperty(FileReader.prototype, 'result', {
          get: function() {
            const res = originalResultGet.call(this);
            if (res && res instanceof ArrayBuffer && this._url) {
              res._url = this._url;
            }
            return res;
          },
          configurable: true,
          enumerable: true
        });
      }
      // Monkeypatch Response.prototype.body getter to pass down the URL to the stream
      const responseBodyDescriptor = Object.getOwnPropertyDescriptor(Response.prototype, 'body');
      if (responseBodyDescriptor && responseBodyDescriptor.get) {
        const originalBodyGet = responseBodyDescriptor.get;
        Object.defineProperty(Response.prototype, 'body', {
          get: function() {
            const bodyStream = originalBodyGet.call(this);
            if (bodyStream && this._url) {
              bodyStream._url = this._url;
            }
            return bodyStream;
          },
          configurable: true,
          enumerable: true
        });
      }

      // Monkeypatch ReadableStream.prototype.getReader
      const originalGetReader = ReadableStream.prototype.getReader;
      ReadableStream.prototype.getReader = function(...args) {
        const reader = originalGetReader.apply(this, args);
        if (this._url) {
          reader._url = this._url;
        }
        return reader;
      };

      // Monkeypatch ReadableStreamDefaultReader.prototype.read
      if (window.ReadableStreamDefaultReader) {
        const originalRead = ReadableStreamDefaultReader.prototype.read;
        ReadableStreamDefaultReader.prototype.read = function(...args) {
          const promise = originalRead.apply(this, args);
          const readerUrl = this._url;
          if (readerUrl) {
            return promise.then(result => {
              if (result && result.value && result.value.buffer) {
                result.value.buffer._url = readerUrl;
              }
              return result;
            });
          }
          return promise;
        };
      }

      // Monkeypatch TypedArray.prototype.set to copy the URL tag during buffer copy/merge
      const TypedArrayProto = Object.getPrototypeOf(Uint8Array).prototype;
      const originalSet = TypedArrayProto.set;
      TypedArrayProto.set = function(source, offset) {
        try {
          if (source && source.buffer && source.buffer._url) {
            this.buffer._url = source.buffer._url;
          }
        } catch(e) {}
        return originalSet.call(this, source, offset);
      };

      // Monkeypatch ArrayBuffer.prototype.slice to copy the URL tag during slice
      const originalSlice = ArrayBuffer.prototype.slice;
      ArrayBuffer.prototype.slice = function(...args) {
        const sliced = originalSlice.apply(this, args);
        if (this._url) {
          sliced._url = this._url;
        }
        return sliced;
      };
    })();
  `;

  const script = document.createElement('script');
  script.textContent = scriptContent;
  const inject = () => {
    const target = document.head || document.documentElement;
    if (target) {
      target.appendChild(script);
    } else {
      setTimeout(inject, 2);
    }
  };
  inject();
}

// 2. DOM-based scraper for assets (Images, Videos) and Creator Profiles
function scanDOM() {
  const assets = [];
  const currentUrl = window.location.href;

  // --- Scan Images ---
  const imgs = document.querySelectorAll('img');
  imgs.forEach(img => {
    const src = img.src || img.getAttribute('data-src') || img.getAttribute('original-src');
    if (!src || src.startsWith('data:') || src.startsWith('blob:')) return;
    
    // Size check
    const width = img.naturalWidth || img.clientWidth || 0;
    const height = img.naturalHeight || img.clientHeight || 0;
    
    // Ignore small icons
    if (width > 0 && height > 0 && (width < 150 || height < 150)) return;
    
    // Determine file title or alt
    const title = img.alt || img.title || '图片素材';
    
    assets.push({
      url: src,
      type: 'image',
      name: title + (src.includes('.webp') ? '.webp' : src.includes('.png') ? '.png' : '.jpg'),
      sizeText: width > 0 ? `${width} x ${height}` : '未知尺寸'
    });
  });

  // --- Scan Videos ---
  const videos = document.querySelectorAll('video');
  videos.forEach((video, index) => {
    let src = video.src || '';
    if (!src) {
      const source = video.querySelector('source');
      if (source) src = source.src || '';
    }
    
    if (src && !src.startsWith('blob:')) {
      assets.push({
        url: src,
        type: 'video',
        name: `视频素材_${index + 1}.mp4`,
        sizeText: 'Direct MP4'
      });
    }
  });

  // Send unique elements back to host
  if (assets.length > 0) {
    // Unique by URL
    const uniqueAssets = Array.from(new Map(assets.map(item => [item.url, item])).values());
    ipcRenderer.sendToHost('dom-assets-scanned', uniqueAssets);
  }
}

// Detect Platform and Creator Profile
function detectCreatorProfile() {
  const url = window.location.href;
  let creator = null;

  // Bilibili space
  if (url.includes('space.bilibili.com/')) {
    const match = url.match(/space\.bilibili\.com\/(\d+)/);
    if (match) {
      const id = match[1];
      const nameEl = document.querySelector('#h-name');
      const avatarEl = document.querySelector('#h-avatar');
      
      const name = nameEl ? nameEl.textContent.trim() : 'B站Up主_' + id;
      const avatar = avatarEl ? avatarEl.src : '';
      
      creator = { id, name, avatar, url, platform: 'bilibili' };
    }
  }
  // Xiaohongshu user profile
  else if (url.includes('xiaohongshu.com/user/profile/')) {
    const match = url.match(/xiaohongshu\.com\/user\/profile\/([^/?#]+)/);
    if (match) {
      const id = match[1];
      // Xiaohongshu selectors
      const nameEl = document.querySelector('.user-name') || document.querySelector('.user-info .name') || document.querySelector('h1') || document.querySelector('.name-detail');
      const avatarEl = document.querySelector('.user-avatar img') || document.querySelector('.avatar-wrapper img') || document.querySelector('.user-info img');
      
      const name = nameEl ? nameEl.textContent.trim() : '小红书博主_' + id.substring(0, 6);
      const avatar = avatarEl ? avatarEl.src : '';
      
      creator = { id, name, avatar, url, platform: 'xiaohongshu' };
    }
  }
  // Douyin user profile
  else if (url.includes('douyin.com/user/')) {
    const match = url.match(/douyin\.com\/user\/([^/?#]+)/);
    if (match) {
      const id = match[1];
      // Douyin selectors
      const nameEl = document.querySelector('h1') || document.querySelector('[class*="username"]') || document.querySelector('.user-name');
      const avatarEl = document.querySelector('[class*="avatar"] img') || document.querySelector('.avatar img');
      
      const name = nameEl ? nameEl.textContent.trim() : '抖音博主_' + id.substring(0, 6);
      let avatar = '';
      if (avatarEl) {
        avatar = avatarEl.src;
      }
      
      creator = { id, name, avatar, url, platform: 'douyin' };
    }
  }
  // YouTube channel profile
  else if (url.includes('youtube.com/') && (url.includes('/@') || url.includes('/channel/') || url.includes('/c/') || url.includes('/user/'))) {
    let id = '';
    const atMatch = url.match(/youtube\.com\/@([^/?#]+)/);
    const channelMatch = url.match(/youtube\.com\/channel\/([^/?#]+)/);
    const cMatch = url.match(/youtube\.com\/c\/([^/?#]+)/);
    const userMatch = url.match(/youtube\.com\/user\/([^/?#]+)/);
    
    if (atMatch) id = '@' + atMatch[1];
    else if (channelMatch) id = channelMatch[1];
    else if (cMatch) id = cMatch[1];
    else if (userMatch) id = userMatch[1];
    
    if (id) {
      const nameEl = document.querySelector('#channel-name yt-formatted-string') || document.querySelector('h1#text') || document.querySelector('.ytd-channel-name') || document.querySelector('meta[property="og:title"]');
      const avatarEl = document.querySelector('ytd-c4-tabbed-header-renderer img#img') || document.querySelector('#avatar img') || document.querySelector('#channel-header img') || document.querySelector('meta[property="og:image"]');
      
      let name = nameEl ? (nameEl.content || nameEl.textContent.trim()) : 'YouTube频道_' + id;
      name = name.replace(/\s*-\s*YouTube/gi, '');
      const avatar = avatarEl ? (avatarEl.content || avatarEl.src) : '';
      
      creator = { id, name, avatar, url, platform: 'youtube' };
    }
  }
  // Zhihu profile
  else if (url.includes('zhihu.com/people/') || url.includes('zhihu.com/org/')) {
    const match = url.match(/zhihu\.com\/(people|org)\/([^/?#]+)/);
    if (match) {
      const id = match[2];
      const nameEl = document.querySelector('.ProfileHeader-name') || document.querySelector('.UserHeader-name') || document.querySelector('h1') || document.querySelector('.ProfileHeader-title h1');
      const avatarEl = document.querySelector('.ProfileHeader-mainAvatar img') || document.querySelector('.Avatar') || document.querySelector('.ProfileHeader-avatar img') || document.querySelector('.UserHeader-avatar img') || document.querySelector('img.Avatar');
      
      const name = nameEl ? nameEl.textContent.trim() : '知乎作者_' + id;
      const avatar = avatarEl ? avatarEl.src : '';
      creator = { id, name, avatar, url, platform: 'zhihu' };
    }
  }

  if (creator) {
    // Send to host
    ipcRenderer.sendToHost('creator-detected', creator);
  }
}

// Scrape following lists from the DOM (alternative if API interception isn't triggered)
function scrapeFollowingList() {
  const url = window.location.href;
  const list = [];
  
  if (url.includes('bilibili.com') && url.includes('relation/follow')) {
    // Bilibili following page
    const items = document.querySelectorAll('.follow-list .list-item');
    items.forEach(item => {
      const avatarEl = item.querySelector('.avatar img');
      const nameEl = item.querySelector('.title');
      const linkEl = item.querySelector('.title');
      
      if (nameEl && linkEl) {
        const name = nameEl.textContent.trim();
        const avatar = avatarEl ? avatarEl.src : '';
        const href = linkEl.getAttribute('href') || '';
        const profileUrl = href.startsWith('http') ? href : 'https:' + href;
        const match = profileUrl.match(/space\.bilibili\.com\/(\d+)/);
        if (match) {
          list.push({ id: match[1], name, avatar, url: profileUrl, platform: 'bilibili' });
        }
      }
    });
  } else if (url.includes('xiaohongshu.com') && url.includes('following')) {
    // XHS following list
    // (Custom DOM scanning for XHS following page)
  }

  if (list.length > 0) {
    ipcRenderer.sendToHost('following-list-scraped', list);
  }
}

// Helper to extract active video title from the page DOM based on platform
function getActiveVideoTitle() {
  const url = window.location.href;
  let title = '';

  try {
    if (url.includes('douyin.com')) {
      // Check active slide container first
      const activeContainer = document.querySelector('div[data-e2e="feed-active-video"]') || document.querySelector('.active-slide') || document.querySelector('.xg-container');
      if (activeContainer) {
        const titleEl = activeContainer.querySelector('h1') || activeContainer.querySelector('.title') || activeContainer.querySelector('.desc') || activeContainer.querySelector('[class*="title"]') || activeContainer.querySelector('[class*="desc"]');
        if (titleEl) title = titleEl.textContent.trim();
      }
      if (!title) {
        const h1El = document.querySelector('h1');
        if (h1El) title = h1El.textContent.trim();
      }
    } else if (url.includes('bilibili.com')) {
      const titleEl = document.querySelector('h1.video-title') || document.querySelector('.video-info-title') || document.querySelector('h1');
      if (titleEl) title = titleEl.textContent.trim();
    } else if (url.includes('youtube.com')) {
      const titleEl = document.querySelector('h1.ytd-watch-metadata') || document.querySelector('#title h1') || document.querySelector('h1');
      if (titleEl) title = titleEl.textContent.trim();
    } else if (url.includes('xiaohongshu.com')) {
      const titleEl = document.querySelector('.title') || document.querySelector('h1') || document.querySelector('.desc');
      if (titleEl) title = titleEl.textContent.trim();
    }
  } catch(e) {}

  // Fallback to document.title
  if (!title) {
    title = document.title;
  }

  // Clean title (remove suffixes)
  if (title) {
    title = title.replace(/\s*-\s*YouTube/gi, '')
                 .replace(/\s*-\s*哔哩哔哩\s*-\s*bilibili/gi, '')
                 .replace(/\s*_\s*哔哩哔哩\s*_\s*bilibili/gi, '')
                 .replace(/\s*-\s*抖音/gi, '');
  }

  // Clean up special characters for filename safety
  title = title.replace(/[\\/:*?"<>|\r\n\t]/g, '_').trim();
  // Limit length
  if (title.length > 60) {
    title = title.substring(0, 60) + '...';
  }

  return title || '视频素材';
}

// 3. Setup Listeners
// 立即执行 Main World 脚本注入，以便在页面脚本运行前拦截所有网络请求
injectMainWorldScript();

// 监听视频播放事件，当用户切换视频（如抖音滚动播放新视频）时发送通知给主窗口清空嗅探列表
document.addEventListener('play', (event) => {
  if (event.target && event.target.tagName === 'VIDEO') {
    const title = getActiveVideoTitle();
    ipcRenderer.sendToHost('video-active-changed', {
      src: event.target.src,
      title: title,
      currentUrl: window.location.href
    });
  }
}, true);

// Check for actively playing video
function checkActiveVideo() {
  try {
    const videos = document.querySelectorAll('video');
    let playingVideo = null;
    for (let v of videos) {
      if (!v.paused && !v.ended && v.readyState >= 2) {
        playingVideo = v;
        break;
      }
    }
    if (!playingVideo && videos.length > 0) {
      playingVideo = videos[0];
    }
    
    if (playingVideo) {
      const title = getActiveVideoTitle();
      ipcRenderer.sendToHost('video-active-changed', {
        src: playingVideo.src,
        title: title,
        currentUrl: window.location.href
      });
    }
  } catch (e) {}
}

window.addEventListener('DOMContentLoaded', () => {

  
  // Scans
  setTimeout(() => {
    scanDOM();
    detectCreatorProfile();
    scrapeFollowingList();
    checkActiveVideo();
  }, 2000);
  
  // Periodic Scan
  setInterval(() => {
    scanDOM();
    detectCreatorProfile();
    checkActiveVideo();
  }, 2000);
});

// Receive Sniffed responses from the page context
window.addEventListener('message', (event) => {
  if (event.data && event.data.source === 'tintin-sniffer') {
    const { type, data } = event.data;
    
    if (type === 'media-detected') {
      const { url, type: mediaType } = data;
      // Get filename from url
      let filename = '素材file';
      try {
        const parsed = new URL(url);
        const pathname = parsed.pathname || '';
        filename = pathname.substring(pathname.lastIndexOf('/') + 1) || 'asset';
      } catch(e) {}
      
      const fileExt = mediaType === 'audio' ? '.mp3' : '.mp4';
      if (!filename.includes('.')) filename += fileExt;

      ipcRenderer.sendToHost('network-media-sniffed', [{
        url,
        type: mediaType,
        name: filename,
        sizeText: '网络流嗅探'
      }]);
    }
    
    if (type === 'mse-segment-appended') {
      const { url, type: mediaType, blobUrl } = data;
      ipcRenderer.sendToHost('mse-segment-appended', {
        url,
        type: mediaType,
        blobUrl
      });
    }
    
    if (type === 'api-response') {
      const { url, payload } = data;
      handleApiResponse(url, payload);
    }
  }
});

// Parse API payloads directly (Highly robust way to sync followings)
function handleApiResponse(url, payload) {
  const list = [];
  
  // Bilibili following API: api.bilibili.com/x/relation/followings
  if (url.includes('api.bilibili.com/x/relation/followings') && payload && payload.data && payload.data.list) {
    payload.data.list.forEach(item => {
      list.push({
        id: String(item.mid),
        name: item.uname,
        avatar: item.face,
        url: `https://space.bilibili.com/${item.mid}`,
        platform: 'bilibili'
      });
    });
  }
  
  // Xiaohongshu following API: /api/sns/web/v1/user/following
  if (url.includes('api/sns/web/v1/user/following') && payload && payload.data && payload.data.users) {
    payload.data.users.forEach(user => {
      list.push({
        id: user.userId,
        name: user.nickname,
        avatar: user.image,
        url: `https://www.xiaohongshu.com/user/profile/${user.userId}`,
        platform: 'xiaohongshu'
      });
    });
  }

  // Douyin following API: aweme/v1/user/following/list
  if (url.includes('aweme/v1/user/following/list') && payload && payload.followings) {
    payload.followings.forEach(user => {
      list.push({
        id: user.sec_uid || user.uid,
        name: user.nickname,
        avatar: user.avatar_thumb?.url_list?.[0] || '',
        url: `https://www.douyin.com/user/${user.sec_uid || user.uid}`,
        platform: 'douyin'
      });
    });
  }

  // TikTok following API: tiktok.com/api/user/list（关注列表）
  if (url.includes('tiktok.com') && url.includes('/api/user/list') && payload && Array.isArray(payload.userList)) {
    payload.userList.forEach(entry => {
      const u = entry.user || entry;
      if (!u) return;
      list.push({
        id: u.secUid || u.id,
        name: u.nickname || u.uniqueId || '未知作者',
        avatar: u.avatarThumb || u.avatarMedium || '',
        url: `https://www.tiktok.com/@${u.uniqueId || ''}`,
        platform: 'tiktok'
      });
    });
  }

  // YouTube subscriptions API: youtubei/v1/guide
  if (url.includes('youtubei/v1/guide') && payload) {
    try {
      const findGuideEntries = (obj) => {
        if (!obj || typeof obj !== 'object') return;
        if (obj.guideEntryRenderer && obj.guideEntryRenderer.entryProperties && obj.guideEntryRenderer.entryProperties.guideEntryHoverText) {
          const entry = obj.guideEntryRenderer;
          const name = entry.formattedTitle.simpleText;
          const channelId = entry.navigationEndpoint.browseEndpoint.browseId;
          const avatar = entry.thumbnail && entry.thumbnail.thumbnails && entry.thumbnail.thumbnails[0] ? entry.thumbnail.thumbnails[0].url : '';
          if (channelId && channelId.startsWith('UC')) {
            list.push({
              id: channelId,
              name: name,
              avatar: avatar,
              url: `https://www.youtube.com/channel/${channelId}`,
              platform: 'youtube'
            });
          }
        } else {
          for (let k in obj) {
            findGuideEntries(obj[k]);
          }
        }
      };
      findGuideEntries(payload);
    } catch(e){}
  }

  // Zhihu followees API: api/v4/members/.../followees
  if (url.includes('api/v4/members/') && url.includes('/followees') && payload && payload.data) {
    payload.data.forEach(item => {
      list.push({
        id: item.url_token || item.id,
        name: item.name,
        avatar: item.avatar_url || item.avatar_url_template?.replace('{size}', 'xl') || '',
        url: `https://www.zhihu.com/people/${item.url_token || item.id}`,
        platform: 'zhihu'
      });
    });
  }

  if (list.length > 0) {
    ipcRenderer.sendToHost('following-list-synced', list);
  }

  // ----------------------------------------------------
  // 以下为博主创作数据列表接口拦截并转发给 Webview Host 的逻辑
  // ----------------------------------------------------

  // Bilibili 创作者视频列表 API 拦截
  if (url.includes('api.bilibili.com/x/space/wbi/arc/search') && payload && payload.data?.list?.vlist) {
    const notes = payload.data.list.vlist.map(item => ({
      id: item.bvid,
      title: item.title,
      url: `https://www.bilibili.com/video/${item.bvid}`,
      cover: item.pic ? (item.pic.startsWith('http') ? item.pic : 'https:' + item.pic) : '',
      date: item.created ? new Date(item.created * 1000).toLocaleString() : '',
      timestamp: item.created ? item.created * 1000 : 0,
      heat: item.play !== undefined ? (typeof item.play === 'number' && item.play >= 10000 ? (item.play / 10000).toFixed(1) + '万播放' : item.play + '播放') : '',
      type: 'video'
    }));
    ipcRenderer.sendToHost('bilibili-user-posted-intercepted', {
      userId: url.match(/mid=(\d+)/)?.[1] || '',
      notes
    });
  }

  if (url.includes('api.bilibili.com/x/polymer/web-space/home/v2') && payload && payload.data?.archive?.item) {
    const notes = payload.data.archive.item.map(item => ({
      id: item.bvid,
      title: item.title,
      url: `https://www.bilibili.com/video/${item.bvid}`,
      cover: item.cover ? (item.cover.startsWith('http') ? item.cover : 'https:' + item.cover) : '',
      date: item.pubdate ? new Date(item.pubdate * 1000).toLocaleString() : '',
      timestamp: item.pubdate ? item.pubdate * 1000 : 0,
      heat: item.stat?.view !== undefined ? (item.stat.view >= 10000 ? (item.stat.view / 10000).toFixed(1) + '万播放' : item.stat.view + '播放') : '',
      type: 'video'
    }));
    ipcRenderer.sendToHost('bilibili-user-posted-intercepted', {
      userId: url.match(/mid=(\d+)/)?.[1] || '',
      notes
    });
  }

  // 小红书创作者发布列表 API 拦截
  if (url.includes('api/sns/web/v1/user_posted') && payload && payload.data?.notes) {
    const notes = payload.data.notes.map(item => {
      const t = item.time || item.createTime || item.updateTime;
      const timestamp = t ? (t < 10000000000 ? t * 1000 : t) : 0;
      return {
        id: item.noteId || item.id,
        title: item.title || item.desc || '小红书笔记',
        url: `https://www.xiaohongshu.com/explore/${item.noteId || item.id}`,
        cover: item.cover?.url || item.cover?.url_pre || '',
        date: timestamp ? new Date(timestamp).toLocaleString() : '',
        timestamp: timestamp,
        heat: item.likes !== undefined ? item.likes + '赞' : (item.likeCount !== undefined ? item.likeCount + '赞' : ''),
        type: item.type === 'video' ? 'video' : 'image'
      };
    });
    ipcRenderer.sendToHost('xhs-user-posted-intercepted', {
      userId: url.match(/user_?id=([^&]+)/i)?.[1] || '',
      notes
    });
  }

  // 抖音创作者视频列表 API 拦截
  if (url.includes('aweme/v1/web/aweme/post') && payload && payload.aweme_list) {
    const notes = payload.aweme_list.map(item => ({
      id: item.aweme_id,
      title: item.desc || '抖音视频',
      url: `https://www.douyin.com/video/${item.aweme_id}`,
      cover: item.video?.cover?.url_list?.[0] || '',
      date: item.create_time ? new Date(item.create_time * 1000).toLocaleString() : '',
      timestamp: item.create_time ? item.create_time * 1000 : 0,
      heat: item.statistics?.digg_count !== undefined ? (item.statistics.digg_count >= 10000 ? (item.statistics.digg_count / 10000).toFixed(1) + '万赞' : item.statistics.digg_count + '赞') : '',
      type: 'video'
    }));
    ipcRenderer.sendToHost('douyin-user-posted-intercepted', {
      secUid: url.match(/sec_user_id=([^&]+)/)?.[1] || '',
      notes
    });
  }

  // TikTok 创作者视频列表 API 拦截：tiktok.com/api/post/item_list
  if (url.includes('tiktok.com') && url.includes('/api/post/item_list') && payload && Array.isArray(payload.itemList)) {
    const notes = payload.itemList.map(item => ({
      id: item.id,
      title: item.desc || 'TikTok 视频',
      url: `https://www.tiktok.com/@${item.author?.uniqueId || ''}/video/${item.id}`,
      cover: item.video?.cover || item.video?.originCover || item.video?.dynamicCover || '',
      date: item.createTime ? new Date(item.createTime * 1000).toLocaleString() : '',
      timestamp: item.createTime ? item.createTime * 1000 : 0,
      heat: item.stats?.diggCount !== undefined ? (item.stats.diggCount >= 10000 ? (item.stats.diggCount / 10000).toFixed(1) + '万赞' : item.stats.diggCount + '赞') : '',
      type: 'video'
    }));
    ipcRenderer.sendToHost('tiktok-user-posted-intercepted', {
      secUid: url.match(/secUid=([^&]+)/)?.[1] || '',
      notes
    });
  }

  // YouTube：youtubei/v1/browse 同时承载「频道视频(关注内容)」与「播放列表(收藏)」，
  // 用页面地址区分：/playlist?list=... → 收藏；/channel|/@|/c → 创作者内容。
  if (url.includes('youtubei/v1/browse') && payload) {
    try {
      const vids = [];
      const seen = new Set();
      const walk = (obj) => {
        if (!obj || typeof obj !== 'object') return;
        const r = obj.videoRenderer || obj.gridVideoRenderer || obj.playlistVideoRenderer ||
                  (obj.richItemRenderer && obj.richItemRenderer.content && obj.richItemRenderer.content.videoRenderer);
        if (r && r.videoId && !seen.has(r.videoId)) {
          seen.add(r.videoId);
          const title = (r.title && (r.title.simpleText ||
                        (r.title.runs && r.title.runs.map(x => x.text).join('')))) || 'YouTube 视频';
          const thumbs = r.thumbnail && r.thumbnail.thumbnails;
          const owner = (r.shortBylineText && r.shortBylineText.runs && r.shortBylineText.runs[0]?.text) ||
                        (r.ownerText && r.ownerText.runs && r.ownerText.runs[0]?.text) || '';
          vids.push({
            id: r.videoId,
            title,
            url: `https://www.youtube.com/watch?v=${r.videoId}`,
            cover: thumbs && thumbs.length ? thumbs[thumbs.length - 1].url : '',
            date: '最新',
            timestamp: 0,
            heat: (r.viewCountText && (r.viewCountText.simpleText || '')) || '',
            type: 'video',
            creatorName: owner
          });
        } else {
          for (const k in obj) walk(obj[k]);
        }
      };
      walk(payload);
      const href = (typeof location !== 'undefined' && location.href) || '';
      if (vids.length > 0) {
        if (href.includes('/playlist')) {
          // 收藏（喜欢的视频 / 稍后观看 / 收藏的播放列表）
          ipcRenderer.sendToHost('kb-collect-items-synced',
            vids.map(v => ({ ...v, platform: 'youtube', isCollected: true,
              creatorName: v.creatorName || '我的收藏' })));
        } else if (href.includes('/channel/') || href.includes('/@') || href.includes('/c/') || href.includes('/user/')) {
          const channelId = (href.match(/\/channel\/(UC[\w-]+)/) || [])[1] || href;
          ipcRenderer.sendToHost('youtube-user-posted-intercepted', { userId: channelId, notes: vids });
        }
      }
    } catch (e) {}
  }

  // 知乎创作者动态/文章列表 API 拦截
  if (url.includes('api/v4/members/') && url.includes('/activities') && payload && payload.data) {
    const notes = payload.data.map(item => {
      const target = item.target;
      if (!target) return null;
      
      let title = target.title || target.excerpt || '知乎内容';
      let type = 'image';
      let postUrl = '';
      let heat = '';
      
      if (target.type === 'answer') {
        title = `[回答] ${target.question?.title || ''}: ${title}`;
        postUrl = `https://www.zhihu.com/question/${target.question?.id}/answer/${target.id}`;
        heat = target.voteup_count !== undefined ? target.voteup_count + '赞同' : '';
      } else if (target.type === 'article') {
        title = `[文章] ${title}`;
        postUrl = target.url || `https://zhuanlan.zhihu.com/p/${target.id}`;
        heat = target.voteup_count !== undefined ? target.voteup_count + '赞同' : '';
      } else if (target.type === 'pin') {
        title = `[想法] ${title}`;
        postUrl = `https://www.zhihu.com/pin/${target.id}`;
        heat = target.like_count !== undefined ? target.like_count + '赞' : '';
      } else if (target.type === 'zvideo') {
        title = `[视频] ${title}`;
        postUrl = `https://www.zhihu.com/zvideo/${target.id}`;
        type = 'video';
        heat = target.play_count !== undefined ? (target.play_count >= 10000 ? (target.play_count / 10000).toFixed(1) + '万播放' : target.play_count + '播放') : '';
      } else {
        postUrl = target.url || '';
      }
      
      return {
        id: String(target.id),
        title: title,
        url: postUrl,
        cover: target.thumbnail || (target.cover ? target.cover : ''),
        date: item.created_time ? new Date(item.created_time * 1000).toLocaleString() : '',
        timestamp: item.created_time ? item.created_time * 1000 : 0,
        heat,
        type
      };
    }).filter(Boolean);

    const userIdMatch = url.match(/members\/([^/]+)/);
    ipcRenderer.sendToHost('zhihu-user-posted-intercepted', {
      userId: userIdMatch ? userIdMatch[1] : '',
      notes
    });
  }

  // 1. 小红书收藏接口拦截 (/api/sns/web/v1/user/collect/page 和 /api/sns/web/v2/board/feed)
  if (url.includes('api/sns/web/v1/user/collect/page') && payload && payload.data && payload.data.notes) {
    const list = payload.data.notes.map(item => {
      const t = item.time || item.createTime || item.updateTime;
      const timestamp = t ? (t < 10000000000 ? t * 1000 : t) : 0;
      return {
        id: item.noteId || item.id,
        title: item.title || item.desc || '小红书笔记',
        url: `https://www.xiaohongshu.com/explore/${item.noteId || item.id}`,
        cover: item.cover?.url || item.cover?.url_pre || '',
        date: timestamp ? new Date(timestamp).toLocaleString() : '最新',
        timestamp: timestamp,
        heat: item.likes !== undefined ? item.likes + '赞' : (item.likeCount !== undefined ? item.likeCount + '赞' : ''),
        type: item.type === 'video' ? 'video' : 'image',
        creatorName: item.user?.nickname || item.author?.nickname || '未知作者',
        creatorHomepageUrl: (item.user?.userid || item.author?.userid) ? `https://www.xiaohongshu.com/user/profile/${item.user?.userid || item.author?.userid}` : '',
        platform: 'xiaohongshu',
        isCollected: true
      };
    });
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  if (url.includes('api/sns/web/v2/board/feed') && payload && payload.data && payload.data.notes) {
    const list = payload.data.notes.map(item => {
      const t = item.time || item.createTime || item.updateTime;
      const timestamp = t ? (t < 10000000000 ? t * 1000 : t) : 0;
      return {
        id: item.noteId || item.id,
        title: item.title || item.desc || '小红书笔记',
        url: `https://www.xiaohongshu.com/explore/${item.noteId || item.id}`,
        cover: item.cover?.url || item.cover?.url_pre || '',
        date: timestamp ? new Date(timestamp).toLocaleString() : '最新',
        timestamp: timestamp,
        heat: item.likes !== undefined ? item.likes + '赞' : (item.likeCount !== undefined ? item.likeCount + '赞' : ''),
        type: item.type === 'video' ? 'video' : 'image',
        creatorName: item.user?.nickname || item.author?.nickname || '未知作者',
        creatorHomepageUrl: (item.user?.userid || item.author?.userid) ? `https://www.xiaohongshu.com/user/profile/${item.user?.userid || item.author?.userid}` : '',
        platform: 'xiaohongshu',
        isCollected: true
      };
    });
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 2. B站收藏夹接口拦截 (/x/v3/fav/resource/list)
  if (url.includes('api.bilibili.com/x/v3/fav/resource/list') && payload && payload.data && payload.data.medias) {
    const list = payload.data.medias.map(item => {
      const timestamp = item.ctime ? item.ctime * 1000 : 0;
      return {
        id: item.bvid || String(item.id),
        title: item.title || 'B站视频',
        url: `https://www.bilibili.com/video/${item.bvid || item.id}`,
        cover: item.cover || item.pic || '',
        date: timestamp ? new Date(timestamp).toLocaleString() : '最新',
        timestamp: timestamp,
        heat: item.cnt_info?.play !== undefined ? (item.cnt_info.play >= 10000 ? (item.cnt_info.play / 10000).toFixed(1) + '万播放' : item.cnt_info.play + '播放') : '',
        type: 'video',
        creatorName: item.upper?.name || '未知作者',
        creatorHomepageUrl: item.upper?.mid ? `https://space.bilibili.com/${item.upper.mid}/video` : '',
        platform: 'bilibili',
        isCollected: true
      };
    });
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 3. 抖音收藏接口拦截 (/aweme/v1/web/collect/)
  if (url.includes('aweme/v1/web/collect/') && payload && (payload.aweme_list || payload.collect_list)) {
    const rawList = payload.aweme_list || payload.collect_list || [];
    const list = rawList.map(item => {
      if (!item) return null;
      return {
        id: item.aweme_id,
        title: item.desc || '抖音视频',
        url: `https://www.douyin.com/video/${item.aweme_id}`,
        cover: item.video?.cover?.url_list?.[0] || '',
        date: item.create_time ? new Date(item.create_time * 1000).toLocaleString() : '最新',
        timestamp: item.create_time ? item.create_time * 1000 : 0,
        heat: item.statistics?.digg_count !== undefined ? (item.statistics.digg_count >= 10000 ? (item.statistics.digg_count / 10000).toFixed(1) + '万赞' : item.statistics.digg_count + '赞') : '',
        stats: { like: item.statistics?.digg_count || 0, play: item.statistics?.play_count || 0, comment: item.statistics?.comment_count || 0, collect: item.statistics?.collect_count || 0, share: item.statistics?.share_count || 0 },
        type: 'video',
        creatorName: item.author?.nickname || '未知作者',
        creatorHomepageUrl: item.author?.sec_uid ? `https://www.douyin.com/user/${item.author.sec_uid}` : '',
        platform: 'douyin',
        isCollected: true
      };
    }).filter(Boolean);
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 4. 知乎收藏夹内容接口拦截 (/api/v4/collections/.../contents)
  if (url.includes('api/v4/collections/') && url.includes('/contents') && payload && payload.data) {
    const list = payload.data.map(item => {
      const content = item.content;
      if (!content) return null;
      
      let title = content.title || content.excerpt || '知乎内容';
      let type = 'image';
      let postUrl = '';
      let heat = '';
      
      if (content.type === 'answer') {
        title = `[回答] ${content.question?.title || ''}: ${title}`;
        postUrl = `https://www.zhihu.com/question/${content.question?.id}/answer/${content.id}`;
        heat = content.voteup_count !== undefined ? content.voteup_count + '赞同' : '';
      } else if (content.type === 'article') {
        title = `[文章] ${title}`;
        postUrl = content.url || `https://zhuanlan.zhihu.com/p/${content.id}`;
        heat = content.voteup_count !== undefined ? content.voteup_count + '赞同' : '';
      } else if (content.type === 'pin') {
        title = `[想法] ${title}`;
        postUrl = `https://www.zhihu.com/pin/${content.id}`;
        heat = content.like_count !== undefined ? content.like_count + '赞' : '';
      } else if (content.type === 'zvideo') {
        title = `[视频] ${title}`;
        postUrl = `https://www.zhihu.com/zvideo/${content.id}`;
        type = 'video';
        heat = content.play_count !== undefined ? (content.play_count >= 10000 ? (content.play_count / 10000).toFixed(1) + '万播放' : content.play_count + '播放') : '';
      } else {
        postUrl = content.url || '';
      }
      
      const timestamp = (item.updated_time || content.updated_time || content.created_time || 0) * 1000;
      
      return {
        id: String(content.id),
        title: title,
        url: postUrl,
        cover: content.thumbnail || (content.cover ? content.cover : ''),
        date: timestamp ? new Date(timestamp).toLocaleString() : '最新',
        timestamp: timestamp,
        heat,
        type,
        creatorName: content.author?.name || '未知作者',
        platform: 'zhihu',
        isCollected: true
      };
    }).filter(Boolean);
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 6. 抖音点赞列表拦截 (/aweme/v1/web/aweme/favorite/)
  if (url.includes('aweme/v1/web/aweme/favorite/') && payload && payload.aweme_list) {
    const list = payload.aweme_list.map(item => {
      if (!item || !item.aweme_id) return null;
      return {
        id: item.aweme_id,
        title: item.desc || '抖音视频',
        url: `https://www.douyin.com/video/${item.aweme_id}`,
        cover: item.video?.cover?.url_list?.[0] || '',
        date: item.create_time ? new Date(item.create_time * 1000).toLocaleString() : '最新',
        timestamp: item.create_time ? item.create_time * 1000 : 0,
        heat: item.statistics?.digg_count !== undefined ? (item.statistics.digg_count >= 10000 ? (item.statistics.digg_count / 10000).toFixed(1) + '万赞' : item.statistics.digg_count + '赞') : '',
        stats: { like: item.statistics?.digg_count || 0, play: item.statistics?.play_count || 0, comment: item.statistics?.comment_count || 0, collect: item.statistics?.collect_count || 0, share: item.statistics?.share_count || 0 },
        type: 'video',
        creatorName: item.author?.nickname || '未知作者',
        creatorHomepageUrl: item.author?.sec_uid ? `https://www.douyin.com/user/${item.author.sec_uid}` : '',
        platform: 'douyin',
        isCollected: false,
        isLiked: true
      };
    }).filter(Boolean);
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 7. 小红书点赞列表拦截 (/api/sns/web/v1/note/like/page)
  if (url.includes('api/sns/web/v1/note/like/page') && payload && payload.data && payload.data.notes) {
    const list = payload.data.notes.map(item => {
      const t = item.time || item.createTime || item.updateTime;
      const timestamp = t ? (t < 10000000000 ? t * 1000 : t) : 0;
      return {
        id: item.noteId || item.id,
        title: item.title || item.desc || '小红书笔记',
        url: `https://www.xiaohongshu.com/explore/${item.noteId || item.id}`,
        cover: item.cover?.url || item.cover?.url_pre || '',
        date: timestamp ? new Date(timestamp).toLocaleString() : '最新',
        timestamp: timestamp,
        heat: item.likes !== undefined ? item.likes + '赞' : (item.likeCount !== undefined ? item.likeCount + '赞' : ''),
        type: item.type === 'video' ? 'video' : 'image',
        creatorName: item.user?.nickname || item.author?.nickname || '未知作者',
        platform: 'xiaohongshu',
        isCollected: false,
        isLiked: true
      };
    });
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // 5. TikTok 收藏/喜欢接口拦截：api/favorite/item_list、api/collection/item_list、api/user/collect
  if (url.includes('tiktok.com') &&
      (url.includes('/api/favorite/item_list') || url.includes('/api/collection/item_list') || url.includes('/api/user/collect')) &&
      payload && Array.isArray(payload.itemList)) {
    const list = payload.itemList.map(item => {
      if (!item || !item.id) return null;
      return {
        id: item.id,
        title: item.desc || 'TikTok 视频',
        url: `https://www.tiktok.com/@${item.author?.uniqueId || ''}/video/${item.id}`,
        cover: item.video?.cover || item.video?.originCover || '',
        date: item.createTime ? new Date(item.createTime * 1000).toLocaleString() : '最新',
        timestamp: item.createTime ? item.createTime * 1000 : 0,
        heat: item.stats?.diggCount !== undefined ? (item.stats.diggCount >= 10000 ? (item.stats.diggCount / 10000).toFixed(1) + '万赞' : item.stats.diggCount + '赞') : '',
        type: 'video',
        creatorName: item.author?.nickname || '未知作者',
        platform: 'tiktok',
        isCollected: true
      };
    }).filter(Boolean);
    if (list.length > 0) {
      ipcRenderer.sendToHost('kb-collect-items-synced', list);
    }
  }

  // ════════════ 热点追踪：各平台热榜接口拦截 → hotspot-items-synced ════════════

  // 抖音热榜：aweme/v1/web/hot/search/list
  if (url.includes('aweme/v1/web/hot/search/list') && payload) {
    const wl = (payload.data && (payload.data.word_list || payload.data.data)) || payload.word_list || [];
    const list = (wl || []).map((w, i) => ({
      platform: 'douyin',
      title: w.word || w.sentence || w.title || '',
      rank: (w.position !== undefined ? w.position + 1 : i + 1),
      hot: w.hot_value || w.hotValue || w.hot_score || 0,
      url: w.word ? `https://www.douyin.com/search/${encodeURIComponent(w.word)}` : '',
    })).filter(x => x.title);
    if (list.length) ipcRenderer.sendToHost('hotspot-items-synced', list);
  }

  // 知乎热榜：api/v3/feed/topstory/hot-lists/total
  if (url.includes('feed/topstory/hot-lists') && payload && Array.isArray(payload.data)) {
    const list = payload.data.map((it, i) => {
      const t = it.target || {};
      return {
        platform: 'zhihu',
        title: t.title || t.title_area?.text || (t.question && t.question.title) || '',
        rank: i + 1,
        hot: it.detail_text || (t.metrics_area && t.metrics_area.text) || '',
        url: t.id ? `https://www.zhihu.com/question/${t.id}` : (it.card_id ? `https://www.zhihu.com/${it.card_id}` : ''),
      };
    }).filter(x => x.title);
    if (list.length) ipcRenderer.sendToHost('hotspot-items-synced', list);
  }

  // 小红书热点：api/sns/web/v1/search/hotlist 或 hot_list
  if (url.includes('sns/web/v1/search/hot') && payload && payload.data) {
    const arr = payload.data.items || payload.data.hot_query || payload.data.list || [];
    const list = (arr || []).map((it, i) => ({
      platform: 'xiaohongshu',
      title: it.title || it.query || it.name || '',
      rank: i + 1,
      hot: it.score || it.hot_value || '',
      url: (it.title || it.query) ? `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(it.title || it.query)}` : '',
    })).filter(x => x.title);
    if (list.length) ipcRenderer.sendToHost('hotspot-items-synced', list);
  }

  // B站热门排行：x/web-interface/ranking 或 /popular
  if (url.includes('x/web-interface/ranking') || url.includes('x/web-interface/popular')) {
    const arr = (payload.data && (payload.data.list || payload.data.item)) || [];
    const list = (arr || []).map((it, i) => ({
      platform: 'bilibili',
      title: it.title || '',
      rank: i + 1,
      hot: it.stat?.view !== undefined ? (it.stat.view >= 10000 ? (it.stat.view / 10000).toFixed(1) + '万播放' : it.stat.view + '播放') : '',
      url: it.bvid ? `https://www.bilibili.com/video/${it.bvid}` : '',
    })).filter(x => x.title);
    if (list.length) ipcRenderer.sendToHost('hotspot-items-synced', list);
  }
}

// Listen for manual sniff requests from the host
ipcRenderer.on('trigger-manual-sniff', () => {
  try {
    scanDOM();
    detectCreatorProfile();
    
    // Find the active playing video and trigger re-detection
    const videos = document.querySelectorAll('video');
    let playingVideo = null;
    for (let v of videos) {
      if (!v.paused && !v.ended) {
        playingVideo = v;
        break;
      }
    }
    if (!playingVideo && videos.length > 0) {
      playingVideo = videos[0];
    }
    
    if (playingVideo) {
      const title = getActiveVideoTitle();
      ipcRenderer.sendToHost('video-active-changed', {
        src: playingVideo.src,
        title: title,
        currentUrl: window.location.href
      });
    }
  } catch (e) {
    console.error('Error during manual sniff:', e);
  }
});
