using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal readonly struct PlatformReplayLayout
    {
        public string LevelId { get; }
        public Vector3 PlatformCenter { get; }
        public Vector3 TrainCenter { get; }
        public Vector3 TrackAxis { get; }
        public Vector3 Outward { get; }
        public float PlatformSpan { get; }
        public float LevelElevation { get; }
        public IReadOnlyList<Vector3> DoorCenters { get; }

        public PlatformReplayLayout(
            string levelId,
            Vector3 platformCenter,
            Vector3 trainCenter,
            Vector3 trackAxis,
            Vector3 outward,
            float platformSpan,
            float levelElevation,
            IReadOnlyList<Vector3> doorCenters)
        {
            LevelId = levelId;
            PlatformCenter = platformCenter;
            TrainCenter = trainCenter;
            TrackAxis = trackAxis;
            Outward = outward;
            PlatformSpan = platformSpan;
            LevelElevation = levelElevation;
            DoorCenters = doorCenters;
        }
    }

    internal static class PlatformReplayLayoutResolver
    {
        private const float PlatformDoorToTrackCenter = 1.72f;

        public static bool TryResolve(ReplayData data, out PlatformReplayLayout layout)
        {
            layout = default;
            if (data == null)
                return false;

            var edges = new List<ReplayEntity>();
            string levelId = null;
            foreach (var entity in data.Entities)
            {
                if (!string.Equals(entity.Kind, "platform_edge", StringComparison.OrdinalIgnoreCase)
                    || entity.LevelIds.Count == 0)
                {
                    continue;
                }
                if (levelId == null)
                    levelId = entity.LevelIds[0];
                if (string.Equals(entity.LevelIds[0], levelId, StringComparison.Ordinal))
                    edges.Add(entity);
            }
            if (edges.Count == 0 || levelId == null)
                return false;

            var level = data.GetLevel(levelId);
            var centers = new List<Vector3>(edges.Count);
            var center = Vector3.zero;
            var minX = float.PositiveInfinity;
            var maxX = float.NegativeInfinity;
            var minZ = float.PositiveInfinity;
            var maxZ = float.NegativeInfinity;
            foreach (var edge in edges)
            {
                var world = data.ToWorld(edge.Geometry.Center.x, edge.Geometry.Center.y, levelId);
                centers.Add(world);
                center += world;
                minX = Mathf.Min(minX, world.x);
                maxX = Mathf.Max(maxX, world.x);
                minZ = Mathf.Min(minZ, world.z);
                maxZ = Mathf.Max(maxZ, world.z);
            }
            center /= edges.Count;

            var spanX = maxX - minX;
            var spanZ = maxZ - minZ;
            var trackAxis = spanX >= spanZ ? Vector3.right : Vector3.forward;
            var platformSpan = Mathf.Max(spanX, spanZ);
            centers.Sort((left, right) =>
                Vector3.Dot(left, trackAxis).CompareTo(Vector3.Dot(right, trackAxis)));

            var levelCenter = Vector3.zero;
            foreach (var point in level.Footprint)
                levelCenter += data.ToWorld(point.x, point.y, levelId);
            levelCenter /= Mathf.Max(1, level.Footprint.Count);

            var outward = center - levelCenter;
            outward -= trackAxis * Vector3.Dot(outward, trackAxis);
            if (outward.sqrMagnitude < 0.001f)
                outward = Vector3.Cross(Vector3.up, trackAxis);
            outward.Normalize();

            // Platform-edge entities are the authoritative platform-door line.  The
            // previous formula first walked to the outer level boundary and then added
            // the train offset, pushing the whole train several metres behind the track
            // and outside the B2 footprint.  Offset directly from the door line so the
            // train-side doors sit just beyond the platform screen doors.
            var trainCenter = center + outward * PlatformDoorToTrackCenter;
            trainCenter.y = level.Elevation;

            layout = new PlatformReplayLayout(
                levelId,
                center,
                trainCenter,
                trackAxis,
                outward,
                platformSpan,
                level.Elevation,
                centers);
            return true;
        }
    }
}
