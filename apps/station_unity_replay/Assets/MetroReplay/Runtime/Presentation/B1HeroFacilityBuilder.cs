using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class B1HeroFacilityBuilder
    {
        public static void Build(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            BuildTicketMachines(parent, center, floorY, materials);
            BuildSecurityCheckpoint(parent, center, floorY, materials);
            BuildServiceCenter(parent, center, floorY, materials);
            BuildPlatformPortal(parent, center, floorY, materials);
            BuildInformationLightboxes(parent, center, floorY, materials);
            BuildEmergencySigns(parent, center, floorY, materials);
        }

        private static void BuildTicketMachines(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("TicketMachineBank").transform;
            root.SetParent(parent, false);
            for (var i = 0; i < 3; i++)
            {
                var x = center.x - 13.0f + i * 1.15f;
                var z = center.z - 7.5f;
                B1HeroGeometryFactory.Box(root, "TicketMachineBody", new Vector3(x, floorY + 0.82f, z),
                    new Vector3(0.88f, 1.64f, 0.62f), materials.WallBlue);
                B1HeroGeometryFactory.Box(root, "TicketMachineSide", new Vector3(x, floorY + 0.82f, z - 0.32f),
                    new Vector3(0.92f, 1.68f, 0.04f), materials.DarkMetal);
                var screen = B1HeroGeometryFactory.Box(root, "TicketScreen",
                    new Vector3(x, floorY + 1.12f, z + 0.325f),
                    new Vector3(0.58f, 0.46f, 0.025f), materials.AdvertisingWhite);
                screen.transform.rotation = Quaternion.Euler(-7f, 0f, 0f);
                B1HeroGeometryFactory.Box(root, "TicketSlot",
                    new Vector3(x, floorY + 0.69f, z + 0.335f),
                    new Vector3(0.44f, 0.055f, 0.025f), materials.DarkMetal);
            }
            B1HeroGeometryFactory.Text(root, "TicketLabel", "自助售票  TICKETS",
                new Vector3(center.x - 11.85f, floorY + 1.96f, center.z - 7.15f), 0.14f, Color.white);
        }

        private static void BuildSecurityCheckpoint(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("SecurityCheckpoint").transform;
            root.SetParent(parent, false);
            var scanner = new Vector3(center.x - 11.8f, floorY + 0.88f, center.z + 1.7f);
            B1HeroGeometryFactory.Box(root, "XRayScannerBody", scanner,
                new Vector3(2.25f, 1.76f, 1.05f), materials.WallBlue);
            B1HeroGeometryFactory.Box(root, "XRayScannerOpening", scanner + new Vector3(0f, 0f, 0.54f),
                new Vector3(1.15f, 0.88f, 0.035f), materials.Black);
            B1HeroGeometryFactory.Box(root, "XRayConveyor",
                new Vector3(scanner.x + 1.85f, floorY + 0.72f, scanner.z),
                new Vector3(1.45f, 0.18f, 0.72f), materials.DarkMetal);
            B1HeroGeometryFactory.Box(root, "SecurityConsole",
                new Vector3(scanner.x - 1.62f, floorY + 0.78f, scanner.z + 0.12f),
                new Vector3(0.72f, 1.18f, 0.62f), materials.BrushedSteel);
            B1HeroGeometryFactory.Box(root, "SecurityDisplay",
                new Vector3(scanner.x - 1.62f, floorY + 1.05f, scanner.z + 0.44f),
                new Vector3(0.52f, 0.34f, 0.035f), materials.AdvertisingWhite);
            B1HeroGeometryFactory.Text(root, "SecurityLabel", "安全检查  SECURITY",
                new Vector3(scanner.x, floorY + 1.98f, scanner.z + 0.57f), 0.12f, Color.white);
        }

        private static void BuildServiceCenter(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("CustomerServiceCenter").transform;
            root.SetParent(parent, false);
            var position = new Vector3(center.x + 11.8f, floorY, center.z - 5.9f);
            B1HeroGeometryFactory.Box(root, "ServiceBack", position + new Vector3(0f, 1.25f, -0.26f),
                new Vector3(3.2f, 2.50f, 0.18f), materials.WallBlue);
            B1HeroGeometryFactory.Box(root, "ServiceGlass", position + new Vector3(0f, 1.36f, 0.02f),
                new Vector3(3.0f, 1.30f, 0.035f), materials.Glass);
            B1HeroGeometryFactory.Box(root, "ServiceCounter", position + new Vector3(0f, 0.72f, 0.42f),
                new Vector3(3.2f, 0.30f, 0.78f), materials.BrushedSteel);
            B1HeroGeometryFactory.Text(root, "ServiceLabel", "客服中心  SERVICE CENTER",
                position + new Vector3(0f, 2.18f, 0.22f), 0.13f, Color.white);
        }

        private static void BuildPlatformPortal(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var portalCenter = new Vector3(center.x + 8.8f, floorY + 1.35f, center.z - 11.0f);
            B1HeroGeometryFactory.Box(parent, "PlatformPortal", portalCenter,
                new Vector3(5.4f, 2.7f, 0.35f), materials.WallBlue);
            B1HeroGeometryFactory.Box(parent, "PlatformPortalOpening",
                new Vector3(portalCenter.x, floorY + 1.18f, portalCenter.z + 0.20f),
                new Vector3(4.35f, 2.25f, 0.08f), materials.Black);
            B1HeroGeometryFactory.Text(parent, "PortalLabel", "站台层  TO TRAINS",
                new Vector3(portalCenter.x, floorY + 2.16f, portalCenter.z + 0.27f), 0.13f, Color.white);
        }

        private static void BuildInformationLightboxes(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var z = center.z - 12.36f;
            BuildGenWorldCampaignLightbox(
                parent,
                new Vector3(center.x, floorY + 1.42f, z),
                materials);
            BuildMetroInformationLightbox(
                parent,
                new Vector3(center.x - 6.5f, floorY + 1.42f, z),
                materials);
        }

        private static void BuildGenWorldCampaignLightbox(
            Transform parent,
            Vector3 center,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("GenWorldCampaignLightbox").transform;
            root.SetParent(parent, false);
            B1HeroGeometryFactory.Box(root, "GenWorldFrame", center,
                new Vector3(3.65f, 2.05f, 0.11f), materials.DarkMetal);
            B1HeroGeometryFactory.Box(root, "GenWorldNavyFace",
                center + new Vector3(0f, 0f, 0.065f),
                new Vector3(3.38f, 1.78f, 0.025f), materials.Sign);

            // Preserve the source artwork's aspect ratio and give the wordmark its own
            // quiet field.  This reads as one curated campaign rather than a pasted logo.
            B1HeroGeometryFactory.Box(root, "GenWorldPerseusArtwork",
                center + new Vector3(-0.77f, 0.10f, 0.092f),
                new Vector3(1.42f, 1.115f, 0.018f), materials.GenWorldPoster);
            B1HeroGeometryFactory.Box(root, "GenWorldDivider",
                center + new Vector3(0.08f, 0.08f, 0.098f),
                new Vector3(0.025f, 1.22f, 0.018f), materials.BlueAccent);
            B1HeroGeometryFactory.Text(root, "GenWorldWordmark", "GENWORLD",
                center + new Vector3(0.82f, 0.30f, 0.112f), 0.125f, Color.white);
            B1HeroGeometryFactory.Text(root, "GenWorldTagline", "PERSEUS · CITY SIMULATION",
                center + new Vector3(0.82f, 0.00f, 0.112f), 0.052f,
                new Color(0.28f, 0.78f, 1f));
            B1HeroGeometryFactory.Text(root, "GenWorldChineseTagline", "城市仿真联合实验",
                center + new Vector3(0.82f, -0.28f, 0.112f), 0.050f,
                new Color(0.78f, 0.84f, 0.91f));
            B1HeroGeometryFactory.Box(root, "GenWorldAccent",
                center + new Vector3(0.82f, -0.54f, 0.101f),
                new Vector3(1.22f, 0.035f, 0.018f), materials.BlueAccent);
        }

        private static void BuildMetroInformationLightbox(
            Transform parent,
            Vector3 center,
            B1HeroMaterialLibrary materials)
        {
            B1HeroGeometryFactory.Box(parent, "InformationLightboxFrame", center,
                new Vector3(3.65f, 2.05f, 0.11f), materials.DarkMetal);
            B1HeroGeometryFactory.Box(parent, "InformationLightboxFace",
                center + new Vector3(0f, 0f, 0.065f),
                new Vector3(3.38f, 1.78f, 0.025f), materials.AdvertisingWhite);
            B1HeroGeometryFactory.Box(parent, "InformationLightboxHeader",
                center + new Vector3(0f, 0.69f, 0.085f),
                new Vector3(3.38f, 0.26f, 0.025f), materials.WallBlue);
            B1HeroGeometryFactory.Text(parent, "InformationLightboxTitle", "运营信息  METRO SERVICE",
                center + new Vector3(0f, 0.69f, 0.105f), 0.095f, Color.white);
            for (var line = 0; line < 4; line++)
            {
                B1HeroGeometryFactory.Box(parent, "InformationRouteLine",
                    center + new Vector3(0f, 0.34f - line * 0.27f, 0.09f),
                    new Vector3(2.65f - line * 0.18f, 0.055f, 0.022f),
                    line == 0 ? materials.BlueAccent : materials.DarkMetal);
            }
        }

        private static void BuildEmergencySigns(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            foreach (var xOffset in new[] { -15.4f, 15.4f })
            {
                B1HeroGeometryFactory.Box(parent, "EmergencyExitSign",
                    new Vector3(center.x + xOffset, floorY + 2.82f, center.z - 10.8f),
                    new Vector3(1.22f, 0.38f, 0.05f), materials.EmergencyGreen);
                B1HeroGeometryFactory.Text(parent, "EmergencyExitLabel", "安全出口  EXIT",
                    new Vector3(center.x + xOffset, floorY + 2.83f, center.z - 10.73f),
                    0.075f, Color.white);
            }
        }
    }
}
