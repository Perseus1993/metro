import * as THREE from "three";
import { clone as cloneSkinned } from "three/addons/utils/SkeletonUtils.js";

const STATE_COLORS = {
  entering_station: 0x2f6f9f,
  queueing_gate: 0xbf8f00,
  passing_gate: 0x7b61b4,
  departed: 0x2f8f5b,
};

export function createActorPool(scene, root, clips, worldToScene) {
  const actors = new Map();
  const prototype = normalizedPrototype(root);

  const update = (passengers, elapsed) => {
    const seen = new Set();
    for (const passenger of passengers) {
      const actor = actorFor(scene, actors, prototype, passenger.id);
      const point = worldToScene([passenger.x, passenger.y]);
      seen.add(passenger.id);
      actor.group.position.set(point.x, 0, point.z);
      actor.group.rotation.y = headingFor(passenger);
      actor.ring.material.color.setHex(STATE_COLORS[passenger.state] || 0x2f6f9f);
      setAction(actor, clips, actionFor(passenger));
      actor.mixer.update(elapsed);
      actor.group.visible = passenger.state !== "departed" || passenger.time_seconds % 7 < 4.5;
    }
    for (const [id, actor] of actors) {
      if (!seen.has(id)) actor.group.visible = false;
    }
  };

  const clear = () => {
    for (const actor of actors.values()) {
      scene.remove(actor.group);
      actor.ring.geometry.dispose();
      actor.ring.material.dispose();
    }
    actors.clear();
  };

  return { clear, update };
}

function actorFor(scene, actors, prototype, id) {
  if (actors.has(id)) return actors.get(id);
  const group = new THREE.Group();
  const model = cloneSkinned(prototype);
  const ring = new THREE.Mesh(
    new THREE.CircleGeometry(0.2, 24),
    new THREE.MeshBasicMaterial({ color: 0x2f6f9f, transparent: true, opacity: 0.7 }),
  );
  ring.rotation.x = -Math.PI / 2;
  group.add(ring, model);
  scene.add(group);
  const actor = {
    group,
    ring,
    mixer: new THREE.AnimationMixer(model),
    actions: new Map(),
    actionName: null,
  };
  actors.set(id, actor);
  return actor;
}

function setAction(actor, clips, nextName) {
  if (actor.actionName === nextName) return;
  const clip = clipFor(clips, nextName);
  if (!clip) return;
  const previous = actor.actions.get(actor.actionName);
  const next = actor.actions.get(nextName) || actor.mixer.clipAction(clip);
  actor.actions.set(nextName, next);
  next.reset().fadeIn(0.12).play();
  previous?.fadeOut(0.12);
  actor.actionName = nextName;
}

function actionFor(passenger) {
  if (passenger.state === "queueing_gate" || passenger.state === "departed") return "Idle_Loop";
  if (passenger.speed < 0.02) return "Idle_Loop";
  return passenger.state === "passing_gate" ? "Walk_Fwd_Loop" : "Jog_Fwd_Loop";
}

function clipFor(clips, name) {
  return clips.find((clip) => clip.name === name)
    || clips.find((clip) => clip.name === "Idle_Loop")
    || clips[0];
}

function headingFor(passenger) {
  const target = Array.isArray(passenger.target) ? passenger.target : [passenger.x + 1, passenger.y];
  const dx = target[0] - passenger.x;
  const dz = target[1] - passenger.y;
  return Math.atan2(dx, dz);
}

function normalizedPrototype(root) {
  const copy = cloneSkinned(root);
  const box = new THREE.Box3().setFromObject(copy);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = 0.78 / Math.max(size.y, 0.001);
  copy.scale.setScalar(scale);
  copy.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
  return copy;
}
