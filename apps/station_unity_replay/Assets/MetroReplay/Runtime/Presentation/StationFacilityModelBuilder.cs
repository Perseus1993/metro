using System;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class StationFacilityModelBuilder
    {
        private readonly Transform _parent;
        private readonly StationFacilityMaterials _materials = new StationFacilityMaterials();

        public StationFacilityModelBuilder(Transform parent)
        {
            _parent = parent;
        }

        public bool TryBuildPlanar(
            string kind, string id, Vector3 baseCenter, float sizeX, float sizeZ,
            float rotationDegrees, out GameObject result)
        {
            if (string.Equals(kind, "gate", StringComparison.OrdinalIgnoreCase))
            {
                result = FarePlatformModelBuilder.BuildFareGates(
                    _parent, id, baseCenter, sizeX, sizeZ, rotationDegrees, _materials);
                return true;
            }
            if (string.Equals(kind, "platform_edge", StringComparison.OrdinalIgnoreCase))
            {
                result = FarePlatformModelBuilder.BuildPlatformDoors(
                    _parent, id, baseCenter, sizeX, sizeZ, rotationDegrees, _materials);
                return true;
            }
            result = null;
            return false;
        }

        public GameObject BuildVertical(
            string kind, string id, Vector3 start, Vector3 end)
        {
            return VerticalFacilityModelBuilder.Build(_parent, id, kind, start, end, _materials);
        }
    }
}
