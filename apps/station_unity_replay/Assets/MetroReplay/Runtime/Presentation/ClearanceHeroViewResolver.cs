using System;
using System.Collections.Generic;
using MetroReplay.Application;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class ClearanceHeroViewResolver
    {
        public static bool TryResolve(
            ReplayData data,
            ReplaySampler sampler,
            out B1HeroView view)
        {
            view = default;
            if (data == null || sampler == null)
                return false;

            var poses = new List<PassengerPose>(Mathf.Max(320, data.ClearanceAudit.TotalPassengers));
            sampler.Sample(0f, poses);
            return TryResolve(data, poses, out view, out _);
        }

        public static bool TryResolve(
            ReplayData data,
            IReadOnlyList<PassengerPose> poses,
            out B1HeroView view,
            out string dominantLevel)
        {
            view = default;
            dominantLevel = null;
            if (data == null || poses == null || poses.Count == 0)
                return false;

            var countByLevel = new Dictionary<string, int>(StringComparer.Ordinal);
            dominantLevel = poses[0].LevelId;
            var dominantCount = 0;
            foreach (var pose in poses)
            {
                countByLevel.TryGetValue(pose.LevelId, out var count);
                count++;
                countByLevel[pose.LevelId] = count;
                if (count > dominantCount)
                {
                    dominantLevel = pose.LevelId;
                    dominantCount = count;
                }
            }

            var initialized = false;
            var bounds = new Bounds();
            foreach (var pose in poses)
            {
                if (!string.Equals(pose.LevelId, dominantLevel, StringComparison.Ordinal))
                    continue;
                if (!initialized)
                {
                    bounds = new Bounds(pose.Position, Vector3.zero);
                    initialized = true;
                }
                else
                {
                    bounds.Encapsulate(pose.Position);
                }
            }
            if (!initialized)
                return false;

            var level = data.GetLevel(dominantLevel);
            var alongX = bounds.size.x >= bounds.size.z;
            var length = Mathf.Max(bounds.size.x, bounds.size.z);
            var forward = alongX ? Vector3.right : Vector3.forward;
            var target = bounds.center + forward * (length * 0.05f);
            target.y = level.Elevation + 1.25f;

            // Look down the longest crowd axis from one end. This keeps individual
            // passengers legible while still showing the depth of the 300-person flow.
            var yaw = alongX ? 100f : 10f;
            var distance = Mathf.Clamp(length * 0.62f, 24f, 48f);
            view = new B1HeroView(target, distance, yaw, 9f);
            return true;
        }
    }
}
