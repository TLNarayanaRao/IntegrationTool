import { activityIconUrl } from "./activityIconUrl";

export default function ActivityIcon({asset}: {asset: string}) {
  return <img className="studio-activity-icon" src={activityIconUrl(asset)} alt="" aria-hidden="true" />;
}
