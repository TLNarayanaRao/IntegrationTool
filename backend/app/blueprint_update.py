"""Reviewed, optimistic-concurrency API updates without replacing implementations."""
from __future__ import annotations
import copy, hashlib, json, os, shutil, tempfile
from pathlib import Path
from .api_blueprint import blueprint_plan, callback_tasks, validate_blueprint
from .models import Project


class UpdateConflict(ValueError):pass


def revision(project):
    value=project.model_dump(mode='json',exclude={'process'})
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def update_plan(project,resource_id,document,selected,*,reference_documents=None,document_path='',response_mode='stub'):
    source=next((resource for resource in project.resources if resource.id==resource_id),None)
    if source is None or source.type!='http' or not source.config.get('apiBlueprintId'):raise ValueError('Select an existing API Blueprint server connection')
    group=source.config['apiBlueprintId'];old=validate_blueprint(source.config.get('openApiDocument'))
    old_operations={operation['operationId']:operation for operation in old['operations']}
    generated=blueprint_plan(document,selected,source.model_dump(),source.name,response_mode,source.package_path,
                             reference_documents=reference_documents,document_path=document_path)
    normalized=generated['resource']['config']['openApiDocument']
    new=validate_blueprint(normalized);new_operations={operation['operationId']:operation for operation in new['operations']}
    members=[]
    for task in project.tasks:
        for activity in task.activities:
            if activity.type=='rest' and activity.config.get('operation')=='receiver' and activity.config.get('resourceId')==resource_id and activity.config.get('apiBlueprintId')==group:
                if activity.config.get('operationId') not in old_operations:raise ValueError('An existing receiver references an unknown operation; repair it before updating')
                members.append((task,activity,old_operations[activity.config['operationId']]))
    if not members:raise ValueError('The selected API has no editable receiver flows')
    candidate=project.model_copy(deep=True);replacement=next(resource for resource in candidate.resources if resource.id==resource_id)
    replacement.config['openApiDocument']=normalized
    report={'resourceId':resource_id,'blueprintId':group,'revision':revision(project),
            'added':[],'updated':[],'unchanged':[],'removed':[],'callbackUpdates':[],
            'warnings':list(generated['warnings']),'conflicts':[]}
    matched=set();task_remap={}
    for task in generated['tasks']:
        if task['kind']!='starter':continue
        incoming=task['activities'][0];operation=new_operations[incoming['config']['operationId']]
        options=[entry for entry in members if entry[2]['operationId']==operation['operationId']]
        if not options:options=[entry for entry in members if (entry[2]['method'],entry[2]['path'])==(operation['method'],operation['path'])]
        if len(options)>1:raise ValueError('An operation matches multiple existing flows; resolve the duplicate before updating')
        record={'operationId':operation['operationId'],'method':operation['method'],'path':operation['path']}
        if options:
            previous,event,old_operation=options[0]
            if previous.id in matched:raise ValueError('Two updated operations match the same implementation')
            matched.add(previous.id);record['taskId']=previous.id;task_remap[task['id']]=previous.id
            preserved=next(item for item in candidate.tasks if item.id==previous.id)
            target=next(item for item in preserved.activities if item.id==event.id)
            target.config.update(operationId=operation['operationId'],resourceId=resource_id,apiBlueprintId=group)
            old_definition=old['document']['paths'][old_operation['path']][old_operation['method'].lower()]
            new_definition=normalized['paths'][operation['path']][operation['method'].lower()]
            changed=old_operation!=operation or old_definition!=new_definition or old['document'].get('components')!=normalized.get('components') or old['document'].get('x-mina-refs')!=normalized.get('x-mina-refs') or old['document'].get('servers')!=normalized.get('servers') or old['document'].get('security')!=normalized.get('security')
            record.update(previousPath=old_operation['path'],previousMethod=old_operation['method'])
            report['updated' if changed else 'unchanged'].append(record)
        else:
            incoming['config'].update(resourceId=resource_id,apiBlueprintId=group)
            candidate.tasks.append(type(project.tasks[0]).model_validate(task));record['taskId']=task['id'];task_remap[task['id']]=task['id']
            report['added'].append(record)
    for task,event,operation in members:
        if task.id not in matched:report['removed'].append({'taskId':task.id,**{key:operation[key] for key in ('operationId','method','path')}})
    if report['removed']:report['conflicts'].append('The update removes existing operations. Their flows have been preserved. Keep these operations in the contract or explicitly resolve their implementations before updating.')
    helpers={}
    for task in project.tasks:
        for activity in task.activities:
            if activity.config.get('apiBlueprintId')==group and activity.config.get('apiBlueprintCallbackKey'):helpers[activity.config['apiBlueprintCallbackKey']]=(task.id,activity.id)
    # Migrate older helpers by their generated IDs, never by a display-name guess.
    for task,event,operation in members:
        declaration=old['document']['paths'][operation['path']][operation['method'].lower()]
        for helper in callback_tasks(old['document'],declaration,task.id):
            existing=next((item for item in project.tasks if item.id==helper['id']),None)
            if existing:
                expected=next(activity for activity in helper['activities'] if activity['config'].get('callbackDelivery'))
                actual=next((activity for activity in existing.activities if activity.id==expected['id'] and activity.config.get('callbackDelivery')),None)
                if actual:helpers.setdefault(expected['config']['apiBlueprintCallbackKey'],(existing.id,actual.id))
    used_helpers=set()
    for helper in generated['tasks']:
        if helper['kind']=='starter':continue
        send=next(activity for activity in helper['activities'] if activity['config'].get('callbackDelivery'))
        key=send['config']['apiBlueprintCallbackKey'];used_helpers.add(key)
        if key in helpers:
            task_id,activity_id=helpers[key]
            preserved=next(task for task in candidate.tasks if task.id==task_id)
            target=next(activity for activity in preserved.activities if activity.id==activity_id)
            for field in ('openApiDocument','operationId','apiBlueprintCallbackKey'):target.config[field]=copy.deepcopy(send['config'][field])
            target.config['apiBlueprintId']=group
            report['callbackUpdates'].append({'taskId':task_id,'name':preserved.name})
        else:
            send['config']['apiBlueprintId']=group
            candidate.tasks.append(type(project.tasks[0]).model_validate(helper))
            report['callbackUpdates'].append({'taskId':helper['id'],'name':helper['name'],'added':True})
    if set(helpers)-used_helpers:report['warnings'].append('Older callback helpers remain unchanged so existing Call Sub Task mappings continue to reference them. Review them before removing obsolete callbacks.')
    # The transport, credentials, task identities, names, packages, reply mappings,
    # groups, variables and all user-added activities/transitions stay untouched.
    from .store import _object_names
    old_names=_object_names(project)
    for scope,entries in _object_names(candidate).items():
        if len(entries)>1 and not entries.keys()<=old_names.get(scope,{}).keys():report['conflicts'].append('An added operation/helper name conflicts with an existing object in its package.')
    report['requiresReview']=bool(report['added'] or report['updated'] or report['removed'] or report['callbackUpdates'])
    report['token']=hashlib.sha256(json.dumps({'revision':report['revision'],'resourceId':resource_id,'document':document,'selected':selected,
        'references':reference_documents,'documentPath':document_path,'responseMode':response_mode},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return candidate,report


def apply_update(project_id,resource_id,document,selected,expected_revision,reviewed=False,preview_token='',**options):
    from . import store
    with store.STORE_LOCK:
        current=store.get_project(project_id)
        if current is None:raise ValueError('Project not found')
        if revision(current)!=expected_revision:raise UpdateConflict('Project changed after the preview. Save your current edits and preview the update again.')
        candidate,report=update_plan(current,resource_id,document,selected,**options)
        if report['token']!=preview_token:raise UpdateConflict('The contract or selection changed after preview. Preview the update again.')
        if report['conflicts']:raise UpdateConflict('; '.join(report['conflicts']))
        if report['requiresReview'] and not reviewed:raise UpdateConflict('Review and acknowledge the contract changes before applying the update.')
        directory=store.project_dir(project_id)
        backup=Path(tempfile.mkdtemp(prefix='.api-update-',dir=store.DATA_DIR))
        if backup.resolve().parent!=store.DATA_DIR.resolve():raise RuntimeError('Unsafe API update backup directory')
        try:
            shutil.copytree(directory,backup/'snapshot')
            try:result=store.save_project(candidate,enforce_names=True)
            except Exception:
                try:
                    os.replace(directory,backup/'failed')
                    os.replace(backup/'snapshot',directory)
                except Exception as error:
                    raise RuntimeError(f'API update failed; recovery snapshot retained at {backup}') from error
                raise
        except RuntimeError:
            # A failed rollback must retain the only recovery copy.
            if not directory.exists() or (backup/'snapshot').exists():raise
            shutil.rmtree(backup,ignore_errors=True);raise
        except Exception:
            shutil.rmtree(backup,ignore_errors=True);raise
        else:
            shutil.rmtree(backup,ignore_errors=True)
        return result,report
