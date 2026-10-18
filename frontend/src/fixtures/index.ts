// Typed access to the generated fixtures the UI uses (the backend also writes run_events.json and
// vault_items.json; nothing here reads them). Regenerate the JSON with:
//   cd backend && uv run python -m pruner.fixtures
// The `as unknown as` casts are needed because JSON imports widen string literals;
// the real shape check happens in backend/tests.
import type { RunSnapshot, VaultGraph } from '../types'
import runSnapshot from './run_snapshot.json'
import vaultGraph from './vault_graph.json'

// FLAG (ignore unless asked): the `as unknown as` casts hide shape drift, so tsc will not catch a mismatch with the backend.
export const fixtureSnapshot = runSnapshot as unknown as RunSnapshot
export const fixtureVaultGraph = vaultGraph as unknown as VaultGraph
