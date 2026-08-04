using System;
using System.IO;
using System.Threading.Tasks;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class StationDecorationLayer : IDisposable
    {
        private readonly RuntimeGltfPrototypeLibrary _library = new RuntimeGltfPrototypeLibrary();

        public int InstanceCount { get; private set; }

        public async Task BuildAsync(Transform stationRoot, ReplayData data, string streamingAssetsPath)
        {
            if (stationRoot == null)
                throw new ArgumentNullException(nameof(stationRoot));
            if (data == null)
                throw new ArgumentNullException(nameof(data));

            var decorRoot = Path.Combine(streamingAssetsPath, "Decor");
            await LoadKenneyAssets(decorRoot);
            await LoadPolyHavenAssets(decorRoot);
            var placement = new StationDecorationPlacement(_library, stationRoot, data);
            InstanceCount = placement.Build();
        }

        public void Dispose()
        {
            _library.Dispose();
        }

        private async Task LoadKenneyAssets(string decorRoot)
        {
            var root = Path.Combine(decorRoot, "KenneyFurnitureKit");
            await _library.LoadAsync(DecorationAssetKeys.Bench, Path.Combine(root, "bench.glb"));
            await _library.LoadAsync(DecorationAssetKeys.TrashCan, Path.Combine(root, "trashcan.glb"));
            await _library.LoadAsync(DecorationAssetKeys.CeilingLamp, Path.Combine(root, "lampSquareCeiling.glb"));
            await _library.LoadAsync(DecorationAssetKeys.Plant, Path.Combine(root, "pottedPlant.glb"));
            await _library.LoadAsync(DecorationAssetKeys.Display, Path.Combine(root, "televisionModern.glb"));
            await _library.LoadAsync(DecorationAssetKeys.CoffeeMachine, Path.Combine(root, "kitchenCoffeeMachine.glb"));
            await _library.LoadAsync(DecorationAssetKeys.Doorway, Path.Combine(root, "doorwayFront.glb"));
        }

        private async Task LoadPolyHavenAssets(string decorRoot)
        {
            var root = Path.Combine(decorRoot, "PolyHaven");
            await _library.LoadAsync(
                DecorationAssetKeys.SecurityCamera,
                Path.Combine(root, "security_camera_01", "security_camera_01_1k.gltf"));
            await _library.LoadAsync(
                DecorationAssetKeys.FireExtinguisher,
                Path.Combine(root, "korean_fire_extinguisher_01", "korean_fire_extinguisher_01_1k.gltf"));
        }
    }

    internal static class DecorationAssetKeys
    {
        public const string Bench = "bench";
        public const string TrashCan = "trashcan";
        public const string CeilingLamp = "ceiling_lamp";
        public const string Plant = "plant";
        public const string Display = "display";
        public const string CoffeeMachine = "coffee_machine";
        public const string Doorway = "doorway";
        public const string SecurityCamera = "security_camera";
        public const string FireExtinguisher = "fire_extinguisher";
    }
}
