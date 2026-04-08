import Lake
open Lake DSL

package «veritas» where
  leanOptions := #[⟨`autoImplicit, false⟩]

lean_lib «Veritas» where
  srcDir := "."

@[default_target]
lean_exe «veritas-core» where
  root := `Veritas.Main
