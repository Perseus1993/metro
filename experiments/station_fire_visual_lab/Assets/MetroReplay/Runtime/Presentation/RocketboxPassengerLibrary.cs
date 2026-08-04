using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class RocketboxPassengerLibrary
    {
        private const string ResourcePath = "PassengerBases/Generated/Prefabs";
        private readonly List<GameObject> _prototypes = new List<GameObject>();
        private readonly List<GameObject> _securityPrototypes = new List<GameObject>();
        private readonly List<GameObject> _operationsPrototypes = new List<GameObject>();

        public IReadOnlyList<GameObject> Prototypes => _prototypes;
        public IReadOnlyList<GameObject> SecurityPrototypes => _securityPrototypes;
        public IReadOnlyList<GameObject> OperationsPrototypes => _operationsPrototypes;
        public int BaseCount => _prototypes.Count;
        public int SecurityBaseCount => _securityPrototypes.Count;
        public int OperationsBaseCount => _operationsPrototypes.Count;
        public int LodLevelCount { get; private set; }

        public static RocketboxPassengerLibrary Load()
        {
            var library = new RocketboxPassengerLibrary();
            var loaded = Resources.LoadAll<GameObject>(ResourcePath);
            Array.Sort(loaded, CompareByIdentity);
            foreach (var prototype in loaded)
            {
                var identity = prototype.GetComponent<PassengerBaseIdentity>();
                if (identity == null)
                    continue;
                if (IsSecurity(identity.BaseId))
                    library._securityPrototypes.Add(prototype);
                else if (IsCommuter(identity.BaseId))
                    library._prototypes.Add(prototype);
                else
                    library._operationsPrototypes.Add(prototype);
                library.LodLevelCount = Mathf.Max(library.LodLevelCount, identity.LodLevelCount);
            }
            return library;
        }

        private static bool IsSecurity(string baseId)
        {
            return !string.IsNullOrWhiteSpace(baseId)
                   && baseId.StartsWith("Security_", StringComparison.Ordinal);
        }

        private static bool IsCommuter(string baseId)
        {
            if (string.IsNullOrWhiteSpace(baseId))
                return false;
            return baseId.StartsWith("Business_", StringComparison.Ordinal)
                   || baseId.StartsWith("Female_Adult_", StringComparison.Ordinal)
                   || baseId.StartsWith("Male_Adult_", StringComparison.Ordinal)
                   || baseId.StartsWith("Female_Child_", StringComparison.Ordinal)
                   || baseId.StartsWith("Male_Child_", StringComparison.Ordinal)
                   || baseId.StartsWith("Female_Party_", StringComparison.Ordinal)
                   || baseId.StartsWith("Sports_", StringComparison.Ordinal);
        }

        private static int CompareByIdentity(GameObject left, GameObject right)
        {
            var leftId = left.GetComponent<PassengerBaseIdentity>()?.BaseId ?? left.name;
            var rightId = right.GetComponent<PassengerBaseIdentity>()?.BaseId ?? right.name;
            return string.Compare(leftId, rightId, StringComparison.Ordinal);
        }
    }
}
