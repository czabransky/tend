{
  description = "Run dev commands in the background as launchd jobs, with an fzf job manager";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      # launchd only, so macOS only.
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: {
        default = pkgs.stdenvNoCC.mkDerivation {
          pname = "tend";
          version = "0.1.0";
          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];
          buildInputs = [ pkgs.python3 ];
          nativeCheckInputs = [ pkgs.python3 ];

          dontBuild = true;
          doCheck = true;
          checkPhase = ''
            runHook preCheck
            python3 -m unittest discover tests
            runHook postCheck
          '';

          # fixupPhase points the shebang at this python3. fzf goes on PATH so the job manager
          # finds a version new enough for its options.
          installPhase = ''
            runHook preInstall
            install -Dm755 tend $out/bin/tend
            wrapProgram $out/bin/tend --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.fzf ]}
            runHook postInstall
          '';

          meta = {
            description = "Run dev commands in the background as launchd jobs, with an fzf job manager";
            license = pkgs.lib.licenses.unlicense;
            platforms = pkgs.lib.platforms.darwin;
            mainProgram = "tend";
          };
        };
      });

      checks = forAllSystems (pkgs: {
        default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      });
    };
}
