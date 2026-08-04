using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal readonly struct B1HeroView
    {
        public Vector3 Target { get; }
        public float Distance { get; }
        public float Yaw { get; }
        public float Pitch { get; }

        public B1HeroView(Vector3 target, float distance, float yaw, float pitch)
        {
            Target = target;
            Distance = distance;
            Yaw = yaw;
            Pitch = pitch;
        }
    }

    internal sealed class B1HeroSceneBuilder
    {
        private const string LevelId = "b1_concourse";
        private readonly Transform _stationRoot;
        private readonly ReplayData _data;
        private readonly bool _preferExitGate;

        public B1HeroSceneBuilder(
            Transform stationRoot,
            ReplayData data,
            bool preferExitGate = false)
        {
            _stationRoot = stationRoot;
            _data = data;
            _preferExitGate = preferExitGate;
        }

        public B1HeroView Build()
        {
            var level = _data.GetLevel(LevelId);
            var gates = FindFareGates();
            var gate = FindPrimaryGate(gates);
            var gateCenter = gate != null
                ? _data.ToWorld(gate.Geometry.Center.x, gate.Geometry.Center.y, LevelId)
                : FallbackGateCenter(level);
            var floorY = level.Elevation + 0.08f;
            var hallCenter = new Vector3(gateCenter.x, floorY, gateCenter.z - 0.35f);
            ResolveShellBounds(level, floorY, out var shellCenter, out var shellWidth, out var shellDepth);
            var bayCenters = ResolveBayCenters(gates, hallCenter, floorY);

            HideB1Placeholders(level, gate);
            var root = new GameObject("B1HeroSample").transform;
            root.SetParent(_stationRoot, false);
            var materials = new B1HeroMaterialLibrary();
            root.gameObject.AddComponent<B1HeroResourceOwner>().Initialize(materials);

            B1HeroArchitectureBuilder.Build(
                root,
                shellCenter,
                hallCenter,
                bayCenters,
                floorY,
                shellWidth,
                shellDepth,
                materials);
            BuildFareGateBanks(root, gates, gateCenter, floorY, materials);
            B1HeroLighting.Build(
                root,
                shellCenter,
                bayCenters,
                floorY,
                shellWidth,
                shellDepth);

            // Keep the fare gates as the visual anchor while leaving enough room in the
            // right third for the vertical-transport bank.  This is a presentation-only
            // camera offset; authoritative replay geometry remains untouched.
            var target = gateCenter + new Vector3(
                _preferExitGate ? 6.5f : 4.8f,
                1.22f,
                -1.0f);
            return new B1HeroView(target, _preferExitGate ? 13.8f : 12.5f, 165f, 3.5f);
        }

        private List<ReplayEntity> FindFareGates()
        {
            var gates = new List<ReplayEntity>();
            foreach (var entity in _data.Entities)
            {
                if (!string.Equals(entity.Kind, "gate", StringComparison.OrdinalIgnoreCase))
                    continue;
                if (entity.LevelIds.Count == 0 || !string.Equals(entity.LevelIds[0], LevelId, StringComparison.Ordinal))
                    continue;
                gates.Add(entity);
            }
            return gates;
        }

        private ReplayEntity FindPrimaryGate(IReadOnlyList<ReplayEntity> gates)
        {
            ReplayEntity fallback = null;
            foreach (var entity in gates)
            {
                fallback ??= entity;
                var isExit = entity.Id.IndexOf("exit", StringComparison.OrdinalIgnoreCase) >= 0;
                if (isExit == _preferExitGate)
                    return entity;
            }
            return fallback;
        }

        private List<Vector3> ResolveBayCenters(
            IReadOnlyList<ReplayEntity> gates,
            Vector3 fallback,
            float floorY)
        {
            var centers = new List<Vector3>();
            foreach (var gate in gates)
            {
                var center = _data.ToWorld(
                    gate.Geometry.Center.x,
                    gate.Geometry.Center.y,
                    LevelId);
                centers.Add(new Vector3(center.x, floorY, center.z - 0.35f));
            }
            if (centers.Count == 0)
                centers.Add(fallback);
            return centers;
        }

        private void ResolveShellBounds(
            ReplayLevel level,
            float floorY,
            out Vector3 center,
            out float width,
            out float depth)
        {
            var min = new Vector3(float.PositiveInfinity, floorY, float.PositiveInfinity);
            var max = new Vector3(float.NegativeInfinity, floorY, float.NegativeInfinity);
            foreach (var point in level.Footprint)
            {
                var world = _data.ToWorld(point.x, point.y, level.Id);
                min = Vector3.Min(min, world);
                max = Vector3.Max(max, world);
            }

            if (float.IsInfinity(min.x))
            {
                center = new Vector3(18f, floorY, -12.5f);
                width = 36f;
                depth = 25f;
                return;
            }

            center = new Vector3((min.x + max.x) * 0.5f, floorY, (min.z + max.z) * 0.5f);
            width = Mathf.Max(36f, max.x - min.x);
            depth = Mathf.Max(25f, max.z - min.z);
        }

        private void BuildFareGateBanks(
            Transform parent,
            IReadOnlyList<ReplayEntity> gates,
            Vector3 fallbackCenter,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            if (gates.Count == 0)
            {
                B1HeroFareGateBuilder.Build(
                    parent, fallbackCenter, 11.4f, floorY, materials,
                    "HeroFareGates", _preferExitGate);
                return;
            }

            foreach (var gate in gates)
            {
                var center = _data.ToWorld(
                    gate.Geometry.Center.x,
                    gate.Geometry.Center.y,
                    LevelId);
                center.y = floorY;
                var isExit = gate.Id.IndexOf("exit", StringComparison.OrdinalIgnoreCase) >= 0;
                B1HeroFareGateBuilder.Build(
                    parent,
                    center,
                    Mathf.Max(4f, gate.Geometry.Width),
                    floorY,
                    materials,
                    isExit ? "HeroExitFareGates" : "HeroEntryFareGates",
                    isExit);
            }
        }

        private Vector3 FallbackGateCenter(ReplayLevel level)
        {
            if (level.Footprint.Count == 0)
                return new Vector3(14f, level.Elevation, -12f);
            var min = new Vector2(float.PositiveInfinity, float.PositiveInfinity);
            var max = new Vector2(float.NegativeInfinity, float.NegativeInfinity);
            foreach (var point in level.Footprint)
            {
                min = Vector2.Min(min, point);
                max = Vector2.Max(max, point);
            }
            return _data.ToWorld(
                Mathf.Lerp(min.x, max.x, 0.22f),
                Mathf.Lerp(min.y, max.y, 0.52f),
                LevelId);
        }

        private void HideB1Placeholders(ReplayLevel level, ReplayEntity primaryGate)
        {
            var minX = float.PositiveInfinity;
            var maxX = float.NegativeInfinity;
            foreach (var point in level.Footprint)
            {
                minX = Mathf.Min(minX, point.x);
                maxX = Mathf.Max(maxX, point.x);
            }
            var levelCenterX = float.IsInfinity(minX) ? 0f : (minX + maxX) * 0.5f;
            var primaryCenterX = primaryGate?.Geometry.Center.x ?? levelCenterX;
            var primaryDirection = primaryCenterX >= levelCenterX ? 1f : -1f;
            foreach (var entity in _data.Entities)
            {
                if (!ContainsLevel(entity, LevelId)
                    || !ShouldHide(entity, levelCenterX, primaryDirection))
                    continue;
                var child = _stationRoot.Find(entity.Id);
                if (child == null)
                    continue;
                foreach (var renderer in child.GetComponentsInChildren<Renderer>(true))
                    renderer.enabled = false;
            }
        }

        private static bool ContainsLevel(ReplayEntity entity, string levelId)
        {
            foreach (var candidate in entity.LevelIds)
            {
                if (string.Equals(candidate, levelId, StringComparison.Ordinal))
                    return true;
            }
            return false;
        }

        private static bool ShouldHide(
            ReplayEntity entity,
            float levelCenterX,
            float primaryDirection)
        {
            var kind = entity.Kind;
            if (string.Equals(kind, "gate", StringComparison.OrdinalIgnoreCase)
                || string.Equals(kind, "queue:lane", StringComparison.OrdinalIgnoreCase)
                || string.Equals(kind, "queue:grid", StringComparison.OrdinalIgnoreCase))
                return true;

            if (!string.Equals(kind, "obstacle", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(kind, "entrance", StringComparison.OrdinalIgnoreCase))
                return false;

            if (entity.Id.IndexOf("fare_barrier", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;

            // The custom hero facilities replace the selected camera bay.  Keep the
            // opposite bay's room shells, ticket machines and entrance visible so the
            // whole B1 concourse stays furnished instead of becoming an empty half.
            var offsetTowardPrimary = (entity.Geometry.Center.x - levelCenterX) * primaryDirection;
            return offsetTowardPrimary > 2f;
        }
    }

    internal sealed class B1HeroResourceOwner : MonoBehaviour
    {
        private B1HeroMaterialLibrary _materials;

        public void Initialize(B1HeroMaterialLibrary materials)
        {
            _materials = materials;
        }

        private void OnDestroy()
        {
            _materials?.Dispose();
        }
    }
}
