import React, { useEffect, useRef, useState } from "react";

import { mountQuaterniusGlbScene } from "./quaternius_glb_scene.js?v=ops-config-1";

const h = React.createElement;

export function QuaterniusGlbPreview() {
  const viewportRef = useRef(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let disposeScene = () => {};
    let cancelled = false;
    const viewport = viewportRef.current;
    const onSceneStatus = (event) => setStatus(event.detail?.status || "failed");
    viewport?.addEventListener("quaternius-glb-scene-status", onSceneStatus);
    Promise.all([import("three"), import("three/addons/loaders/GLTFLoader.js")])
      .then(([THREE, loaderModule]) => {
        if (cancelled || !viewportRef.current) return;
        disposeScene = mountQuaterniusGlbScene(THREE, loaderModule.GLTFLoader, viewportRef.current);
      })
      .catch(() => setStatus("failed"));
    return () => {
      cancelled = true;
      viewport?.removeEventListener("quaternius-glb-scene-status", onSceneStatus);
      disposeScene();
    };
  }, []);

  return h("div", { className: "quaternius-glb-preview" }, [
    h("div", { key: "head", className: "quaternius-glb-preview__head" }, [
      h("strong", { key: "title" }, "GLB 骨骼预览"),
      h("span", { key: "status" }, statusLabel(status)),
    ]),
    h("div", { key: "viewport", className: "quaternius-glb-preview__viewport", ref: viewportRef }, [
      status === "failed"
        ? h("div", { key: "fallback", className: "quaternius-glb-preview__fallback" }, "GLB 加载失败")
        : null,
    ]),
  ]);
}

function statusLabel(status) {
  if (status === "ready") return "Jog_Fwd_Loop";
  if (status === "failed") return "不可用";
  return "加载中";
}
