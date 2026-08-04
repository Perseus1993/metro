(function () {
  const DEFAULT_IMAGE = "assets/passenger_sprite_atlas.png";
  const DEFAULT_META = "assets/passenger_sprite_atlas.json";
  const WAIT_DIAGNOSTICS = new Set(["queue", "platform_wait"]);
  const WALK_SPEED_PX_PER_SEC = 5.5;

  const state = {
    image: null,
    meta: null,
    ready: false,
    promise: null,
    error: null,
  };

  function loadPassengerSprites(options = {}) {
    if (state.promise) return state.promise;
    const imageUrl = options.imageUrl || DEFAULT_IMAGE;
    const metaUrl = options.metaUrl || DEFAULT_META;

    state.promise = Promise.all([loadImage(imageUrl), loadJson(metaUrl)])
      .then(([image, meta]) => {
        state.image = image;
        state.meta = meta;
        state.ready = true;
        state.error = null;
        return state;
      })
      .catch((error) => {
        state.ready = false;
        state.error = error;
        return state;
      });

    return state.promise;
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error(`Could not load passenger atlas: ${src}`));
      image.src = src;
    });
  }

  function loadJson(src) {
    if (typeof fetch === "function") {
      return fetch(src).then((response) => {
        if (!response.ok) throw new Error(`Could not load passenger atlas metadata: ${src}`);
        return response.json();
      }).catch(() => loadJsonWithXhr(src));
    }
    return loadJsonWithXhr(src);
  }

  function loadJsonWithXhr(src) {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("GET", src, true);
      request.onload = () => {
        if (request.status < 200 || request.status >= 300) {
          reject(new Error(`Could not load passenger atlas metadata: ${src}`));
          return;
        }
        try {
          resolve(JSON.parse(request.responseText));
        } catch (error) {
          reject(error);
        }
      };
      request.onerror = () => reject(new Error(`Could not load passenger atlas metadata: ${src}`));
      request.send();
    });
  }

  function isReady() {
    return state.ready && state.image && state.meta;
  }

  function passengerTypeId(agent) {
    const types = Array.isArray(state.meta?.types) ? state.meta.types : [];
    if (!types.length) return null;
    const rawId = Number.isFinite(Number(agent?.group_id))
      ? Number(agent.group_id)
      : Number.isFinite(Number(agent?.id))
        ? Number(agent.id)
        : 0;
    const index = Math.abs(Math.trunc(rawId)) % types.length;
    return types[index].id;
  }

  function passengerAction(point) {
    if (!point) return "walk";
    if (WAIT_DIAGNOSTICS.has(point.diagnostic)) return "queue";
    return point.speed > WALK_SPEED_PX_PER_SEC ? "walk" : "queue";
  }

  function passengerDirection(angle) {
    const radians = Number(angle);
    if (!Number.isFinite(radians)) return "down";
    const dx = Math.cos(radians);
    const dy = Math.sin(radians);
    if (Math.abs(dx) > Math.abs(dy)) return dx >= 0 ? "right" : "left";
    return dy >= 0 ? "down" : "up";
  }

  function passengerFrame(agent, point, localTime, action) {
    const motion = agent?.motion || {};
    const phase = Number(motion.phase) || 0;
    const seed = Number.isFinite(Number(agent?.id)) ? Number(agent.id) : 0;
    const frameCount = Math.max(1, Number(state.meta?.frame_count) || 4);
    if (action === "queue") {
      return Math.floor((localTime * 1.1 + seed * 0.17 + phase) % frameCount);
    }
    const strideHz = Number(motion.stride_hz) || 1.45;
    return Math.floor((localTime * strideHz * frameCount + phase) % frameCount);
  }

  function drawPassengerSprite(ctx, options) {
    if (!isReady()) return false;
    const agent = options.agent || {};
    const point = options.point || {};
    const localTime = Number(options.localTime) || 0;
    const typeId = options.typeId || passengerTypeId(agent);
    const action = options.action || passengerAction(point);
    const direction = options.direction || passengerDirection(options.angle ?? point.angle);
    const frameIndex = options.frameIndex ?? passengerFrame(agent, point, localTime, action);
    const frame = state.meta.frames?.[`${typeId}/${action}/${direction}/${frameIndex}`];
    if (!frame) return false;

    const scale = (Number(agent.size) || 1) * (Number(options.scale) || Number(state.meta.render_scale) || 0.48);
    const anchor = Array.isArray(frame.anchor) ? frame.anchor : [frame.w / 2, frame.h * 0.78];
    const x = Number(options.x);
    const y = Number(options.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;

    ctx.save();
    ctx.globalAlpha = Math.min(1, Math.max(0, Number(options.alpha ?? point.alpha ?? 1)));
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(
      state.image,
      frame.x,
      frame.y,
      frame.w,
      frame.h,
      x - anchor[0] * scale,
      y - anchor[1] * scale,
      frame.w * scale,
      frame.h * scale,
    );
    ctx.restore();
    return true;
  }

  window.PassengerSpriteLibrary = {
    load: loadPassengerSprites,
    isReady,
    draw: drawPassengerSprite,
    directionForAngle: passengerDirection,
    actionForPoint: passengerAction,
    state,
  };
})();
