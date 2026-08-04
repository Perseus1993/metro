(() => {
  "use strict";

  const COLORS = {
    ink: "#dff3f7", muted: "#6f929e", cyan: "#47d7e8", green: "#75e6a4",
    amber: "#ffcc66", orange: "#ff8c5a", concourse: "#102832", platform: "#12242d",
  };

  const frameAt = (frames, time) => {
    if (time <= 0) return frames[0];
    const last = frames[frames.length - 1];
    if (time >= last.time_seconds) return last;
    let high = frames.findIndex((frame) => frame.time_seconds >= time);
    if (high <= 0) return frames[0];
    const left = frames[high - 1];
    const right = frames[high];
    if (left.level_id !== right.level_id || left.passenger_state !== right.passenger_state) return left;
    const span = Math.max(0.001, right.time_seconds - left.time_seconds);
    const ratio = (time - left.time_seconds) / span;
    return {
      ...left,
      position: left.position.map((value, index) => value + (right.position[index] - value) * ratio),
      target: left.target.map((value, index) => value + (right.target[index] - value) * ratio),
    };
  };

  const geometry = (canvas, data) => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(640, rect.width);
    const height = Math.max(360, rect.height);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const padX = 48;
    const scaleX = (width - padX * 2) / data.world.width;
    const floorY = { concourse: height * 0.31, platform: height * 0.73 };
    const point = (position, level) => [
      padX + position[0] * scaleX,
      floorY[level] + (position[1] - 7) * Math.min(10, height / 58),
    ];
    return { ctx, width, height, point, floorY, scaleX, padX };
  };

  const roundedRect = (ctx, x, y, width, height, radius) => {
    ctx.beginPath();
    ctx.roundRect(x, y, width, height, radius);
    ctx.fill();
  };

  const drawFloors = (g) => {
    const { ctx, width, height, floorY } = g;
    [["concourse", "站厅层 / CONCOURSE", COLORS.concourse], ["platform", "站台层 / PLATFORM", COLORS.platform]].forEach(([level, label, color]) => {
      const y = floorY[level] - height * 0.13;
      ctx.fillStyle = color;
      roundedRect(ctx, 25, y, width - 50, height * 0.26, 12);
      ctx.fillStyle = COLORS.muted;
      ctx.font = "700 10px Segoe UI, Microsoft YaHei";
      ctx.fillText(label, 39, y + 19);
      ctx.strokeStyle = "rgba(160,205,216,.08)";
      ctx.setLineDash([4, 7]);
      ctx.beginPath(); ctx.moveTo(38, floorY[level]); ctx.lineTo(width - 38, floorY[level]); ctx.stroke();
      ctx.setLineDash([]);
    });
  };

  const drawRegions = (g, data) => {
    const labels = { entry_gate_decision: "闸机决策", paid_hall: "付费区", vertical_decision: "楼梯决策", platform_landing: "站台落点", boarding_decision: "车门决策" };
    Object.entries(data.regions).forEach(([id, position]) => {
      const level = ["platform_landing", "boarding_decision"].includes(id) ? "platform" : "concourse";
      const [x, y] = g.point(position, level);
      g.ctx.strokeStyle = "rgba(255,204,102,.28)";
      g.ctx.setLineDash([3, 4]);
      g.ctx.beginPath(); g.ctx.arc(x, y, 16, 0, Math.PI * 2); g.ctx.stroke();
      g.ctx.setLineDash([]);
      g.ctx.fillStyle = COLORS.muted; g.ctx.font = "10px Microsoft YaHei";
      g.ctx.fillText(labels[id], x - 22, y - 23);
    });
  };

  const drawFacilities = (g, data) => {
    const ctx = g.ctx;
    data.facilities.forEach((facility) => {
      if (facility.kind === "stairs") return;
      const [x, y] = g.point(facility.position, facility.entry_level);
      ctx.fillStyle = facility.kind === "gate" ? "#2d6575" : "#b85d3d";
      roundedRect(ctx, x - 5, y - 17, 10, 34, 3);
      ctx.fillStyle = COLORS.muted; ctx.font = "9px monospace";
      ctx.fillText(facility.id, x - 17, y + 29);
    });
    const stairs = data.facilities.find((item) => item.id === "stairs_1");
    const entry = g.point(stairs.position, "concourse");
    const exit = g.point(stairs.exit_position, "platform");
    ctx.strokeStyle = "#8da9b3"; ctx.lineWidth = 5;
    ctx.beginPath(); ctx.moveTo(...entry); ctx.lineTo(...exit); ctx.stroke();
    ctx.strokeStyle = "rgba(7,16,21,.8)"; ctx.lineWidth = 1;
    for (let step = 1; step < 8; step += 1) {
      const ratio = step / 8;
      const x = entry[0] + (exit[0] - entry[0]) * ratio;
      const y = entry[1] + (exit[1] - entry[1]) * ratio;
      ctx.beginPath(); ctx.moveTo(x - 5, y); ctx.lineTo(x + 5, y); ctx.stroke();
    }
    ctx.lineWidth = 1;
  };

  const drawTrain = (g, frame) => {
    const ctx = g.ctx; const y = g.floorY.platform + 56;
    ctx.strokeStyle = "rgba(170,201,211,.22)";
    ctx.beginPath(); ctx.moveTo(35, y + 28); ctx.lineTo(g.width - 35, y + 28); ctx.stroke();
    if (frame.train_state !== "boarding") {
      ctx.fillStyle = COLORS.muted; ctx.font = "10px Microsoft YaHei";
      ctx.fillText("列车未到站", g.width - 108, y + 18); return;
    }
    ctx.fillStyle = "#d7e5e9";
    roundedRect(ctx, g.width * 0.72, y - 15, g.width * 0.24, 48, 8);
    ctx.fillStyle = "#21434e";
    [0.75, 0.82, 0.89].forEach((ratio) => roundedRect(ctx, g.width * ratio, y - 6, 31, 25, 3));
    ctx.fillStyle = "#12242d"; ctx.font = "800 10px monospace";
    ctx.fillText(`TRAIN · LOAD ${frame.train_load}`, g.width * 0.735, y + 29);
  };

  const drawCrowd = (g, frame) => {
    const ctx = g.ctx;
    (frame.crowd || []).forEach((actor) => {
      const [, xValue, yValue, level, role] = actor;
      const [x, y] = g.point([xValue, yValue], level);
      ctx.fillStyle = role === "blocker" ? "rgba(255,140,90,.78)" : "rgba(164,193,202,.48)";
      ctx.beginPath(); ctx.arc(x, y, role === "blocker" ? 3.3 : 2.5, 0, Math.PI * 2); ctx.fill();
    });
  };

  const drawPassenger = (g, data, frame, time) => {
    const ctx = g.ctx; const level = frame.level_id || "concourse";
    const [x, y] = g.point(frame.position, level);
    const target = g.point(frame.target, level);
    ctx.strokeStyle = "rgba(255,204,102,.7)"; ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.arc(target[0], target[1], 7, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    const recent = data.frames.filter((item) => item.time_seconds <= time && item.time_seconds >= time - 4 && item.level_id === level);
    ctx.strokeStyle = "rgba(71,215,232,.24)"; ctx.lineWidth = 2; ctx.beginPath();
    recent.forEach((item, index) => { const point = g.point(item.position, level); index ? ctx.lineTo(...point) : ctx.moveTo(...point); }); ctx.stroke();
    const pulse = 11 + Math.sin(time * 5) * 2;
    ctx.fillStyle = "rgba(71,215,232,.14)"; ctx.beginPath(); ctx.arc(x, y, pulse, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = COLORS.cyan; ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = COLORS.ink; ctx.font = "800 9px monospace"; ctx.fillText("P1", x + 10, y - 9);
  };

  const draw = (canvas, data, time) => {
    const frame = frameAt(data.frames, time); const g = geometry(canvas, data);
    g.ctx.clearRect(0, 0, g.width, g.height);
    drawFloors(g); drawRegions(g, data); drawFacilities(g, data); drawTrain(g, frame);
    drawCrowd(g, frame);
    drawPassenger(g, data, frame, time);
    return frame;
  };

  window.GoalJourneyScene = { draw, frameAt };
})();
