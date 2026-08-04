using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class StationDecorationGeometry
    {
        public static void GetPlanarLayout(
            ReplayData data,
            ReplayEntity entity,
            out Vector3 center,
            out Vector3 size,
            out Vector3 longAxis,
            out float length)
        {
            var levelId = entity.LevelIds[0];
            center = data.ToWorld(entity.Geometry.Center.x, entity.Geometry.Center.y, levelId, 0.02f);
            var min = new Vector3(float.PositiveInfinity, 0f, float.PositiveInfinity);
            var max = new Vector3(float.NegativeInfinity, 0f, float.NegativeInfinity);
            foreach (var point in entity.Geometry.Points)
            {
                var world = data.ToWorld(point.x, point.y, levelId);
                min = Vector3.Min(min, world);
                max = Vector3.Max(max, world);
            }
            if (entity.Geometry.Points.Count == 0)
            {
                min = center - new Vector3(entity.Geometry.Width, 0f, entity.Geometry.Height) * 0.5f;
                max = center + new Vector3(entity.Geometry.Width, 0f, entity.Geometry.Height) * 0.5f;
            }
            size = max - min;
            longAxis = size.x >= size.z ? Vector3.right : Vector3.forward;
            length = Mathf.Max(size.x, size.z);
        }

        public static void GetLevelBounds(
            ReplayData data,
            ReplayLevel level,
            out Vector3 center,
            out Vector3 size)
        {
            var min = new Vector3(float.PositiveInfinity, level.Elevation, float.PositiveInfinity);
            var max = new Vector3(float.NegativeInfinity, level.Elevation, float.NegativeInfinity);
            foreach (var point in level.Footprint)
            {
                var world = data.ToWorld(point.x, point.y, level.Id);
                min = Vector3.Min(min, world);
                max = Vector3.Max(max, world);
            }
            center = (min + max) * 0.5f;
            size = max - min;
        }

        public static Quaternion RotationFor(Vector3 longAxis)
        {
            return Mathf.Abs(longAxis.x) > 0.5f
                ? Quaternion.identity
                : Quaternion.Euler(0f, 90f, 0f);
        }
    }
}
