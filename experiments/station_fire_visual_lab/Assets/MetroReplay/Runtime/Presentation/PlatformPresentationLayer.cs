using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class PlatformPresentationLayer : IDisposable
    {
        private readonly List<Material> _materials = new List<Material>();
        private GameObject _root;

        public int InstanceCount { get; private set; }

        public bool Build(Transform parent, ReplayData data, out B1HeroView heroView)
        {
            heroView = default;
            if (parent == null || !PlatformReplayLayoutResolver.TryResolve(data, out var layout))
                return false;

            _root = new GameObject("PlatformPresentationLayer");
            _root.transform.SetParent(parent, false);
            var tactile = CreateMaterial("Platform tactile paving", new Color(0.88f, 0.63f, 0.08f));
            var white = CreateMaterial("Platform waiting line", new Color(0.82f, 0.87f, 0.91f));
            var blue = CreateMaterial("Platform line blue", new Color(0.04f, 0.28f, 0.62f));
            var sign = CreateMaterial("Platform wayfinding sign", new Color(0.018f, 0.025f, 0.036f));
            var interior = -layout.Outward;
            PlaceAlongTrack(
                _root.transform,
                "PlatformTactileSafetyLine",
                layout.PlatformCenter + interior * 0.66f + Vector3.up * 0.035f,
                layout.PlatformSpan + 5.6f,
                0.42f,
                0.035f,
                layout.TrackAxis,
                tactile);
            PlaceAlongTrack(
                _root.transform,
                "PlatformWhiteEdgeLine",
                layout.PlatformCenter + interior * 0.28f + Vector3.up * 0.045f,
                layout.PlatformSpan + 5.8f,
                0.075f,
                0.025f,
                layout.TrackAxis,
                white);

            for (var index = 0; index < layout.DoorCenters.Count; index++)
            {
                var door = layout.DoorCenters[index];
                BuildWaitingMarker(
                    _root.transform,
                    door,
                    interior,
                    layout.TrackAxis,
                    index + 1,
                    blue,
                    white);
            }

            var signCenter = layout.PlatformCenter + interior * 2.9f + Vector3.up * 3.05f;
            PlaceAlongTrack(
                _root.transform,
                "PlatformDirectionSign",
                signCenter,
                6.2f,
                0.13f,
                0.64f,
                layout.TrackAxis,
                sign);
            B1HeroGeometryFactory.Text(
                _root.transform,
                "PlatformDirectionLabel",
                "2号线  往市中心  |  LINE 2  CITY CENTER  →",
                signCenter + layout.Outward * 0.075f,
                0.12f,
                Color.white);

            // Frame the clear door bay between the elevator and east escalator.
            // This keeps the real circulation geometry in place while presenting
            // the platform/train interface without a vertical core in the sightline.
            var forward = (layout.Outward - layout.TrackAxis * 0.08f).normalized;
            var yaw = Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg;
            var target = layout.PlatformCenter
                + layout.TrackAxis * 16.5f
                + layout.Outward * 1.0f
                + Vector3.up * 1.35f;
            heroView = new B1HeroView(target, 12.8f, yaw, 5.0f);
            return true;
        }

        public void Dispose()
        {
            if (_root != null)
                DestroyObject(_root);
            foreach (var material in _materials)
                DestroyObject(material);
            _materials.Clear();
        }

        private void BuildWaitingMarker(
            Transform parent,
            Vector3 door,
            Vector3 interior,
            Vector3 trackAxis,
            int number,
            Material blue,
            Material white)
        {
            var markerCenter = door + interior * 1.52f + Vector3.up * 0.052f;
            PlaceAlongTrack(parent, "PlatformQueueMarker_" + number, markerCenter,
                1.65f, 1.28f, 0.022f, trackAxis, blue);
            PlaceAlongTrack(parent, "PlatformQueueMarkerInner_" + number,
                markerCenter + Vector3.up * 0.012f,
                1.45f, 1.08f, 0.018f, trackAxis, white);
            PlaceAlongTrack(parent, "PlatformQueueMarkerCenter_" + number,
                markerCenter + Vector3.up * 0.024f,
                0.16f, 1.12f, 0.012f, trackAxis, blue);

            for (var side = -1; side <= 1; side += 2)
            {
                var laneCenter = door
                    + trackAxis * (side * 0.58f)
                    + interior * 2.45f
                    + Vector3.up * 0.047f;
                PlaceAlongDirection(parent, "PlatformQueueGuide_" + number + "_" + side,
                    laneCenter, interior, 2.9f, 0.055f, 0.016f, blue);
            }
        }

        private Material CreateMaterial(string name, Color color)
        {
            var material = ReplayMaterialFactory.Create(name, color);
            if (material.HasProperty("_Smoothness"))
                material.SetFloat("_Smoothness", 0.52f);
            _materials.Add(material);
            return material;
        }

        private void PlaceAlongTrack(
            Transform parent,
            string name,
            Vector3 center,
            float length,
            float width,
            float height,
            Vector3 trackAxis,
            Material material)
        {
            PlaceAlongDirection(parent, name, center, trackAxis, length, width, height, material);
        }

        private void PlaceAlongDirection(
            Transform parent,
            string name,
            Vector3 center,
            Vector3 direction,
            float length,
            float width,
            float height,
            Material material)
        {
            var item = B1HeroGeometryFactory.Box(
                parent,
                name,
                center,
                new Vector3(length, height, width),
                material);
            item.transform.rotation = Quaternion.FromToRotation(Vector3.right, direction.normalized);
            InstanceCount++;
        }

        private static void DestroyObject(UnityEngine.Object target)
        {
            if (target == null)
                return;
            if (UnityEngine.Application.isEditor)
                UnityEngine.Object.DestroyImmediate(target);
            else
                UnityEngine.Object.Destroy(target);
        }
    }
}
