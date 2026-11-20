import { ArrowLeft, ArrowRight } from "lucide-react";
import type { NavigationActions } from "./studioNavigation";

export function RecentLocations({ recent, jump }: Pick<NavigationActions, "recent" | "jump">) {
  return <select className="recent-locations" aria-label="Recent locations" title="Recent locations"
    disabled={!recent.length} value="" onChange={event => {
      if (event.currentTarget.value) jump(Number(event.currentTarget.value));
    }}>
    <option value="" disabled>Recent locations</option>
    {recent.map(entry => <option key={entry.index} value={entry.index}>{entry.label}</option>)}
  </select>;
}

export default function EditorNavigation({ actions, isDirty }: {
  actions: NavigationActions; isDirty: () => boolean;
}) {
  const move = (action?: () => void) => {
    if (action && (!isDirty() || window.confirm("Leave this editor and discard unsaved changes?"))) action();
  };
  return <span className="editor-navigation" role="group" aria-label="Studio navigation">
    <button type="button" aria-label="Back" title="Back" disabled={!actions.back} onClick={() => move(actions.back)}><ArrowLeft/></button>
    <button type="button" aria-label="Forward" title="Forward" disabled={!actions.forward} onClick={() => move(actions.forward)}><ArrowRight/></button>
    <RecentLocations recent={actions.recent} jump={index => move(() => actions.jump(index))}/>
  </span>;
}
