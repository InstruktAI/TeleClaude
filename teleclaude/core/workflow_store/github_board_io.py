"""GitHub Projects requests for one repository's board, made as the project's platform App.

Every request is a GraphQL document with variables, never an interpolated id, run through the shared
transport so credentials, refusals and rate limits behave as for the issue and pull request reflections.
The board is a reflection: nothing here is read back as workflow state. Setup and item application
compose these primitives inside `submit`, which holds the unit lock for the whole unit; each primitive's
request takes the process-wide request lock alone, like every store request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import Any, cast

from githubkit.exception import GraphQLFailed
from githubkit_schemas.v2026_03_10.types import AppPermissionsType

from teleclaude.core.workflow_store.github import GitHubRepositoryIdentity
from teleclaude.core.workflow_store.github_io_models import (
    GitHubBoardOwner,
    GitHubBoardProject,
    GitHubBoardSelectField,
    GitHubBoardState,
    GitHubBoardView,
    GitHubRepositoryScope,
)
from teleclaude.core.workflow_store.github_io_transport import (
    GitHubIOFailure,
    GitHubIORefused,
    GitHubTransport,
    split_repository,
)
from teleclaude.core.workflow_store.github_io_unit import submit_serialized_unit
from teleclaude.types.github_account import GitHubAccountKind, github_app_bot_login
from teleclaude.types.github_binding import GitHubActorAssignment

_BOARD_PERMISSIONS: AppPermissionsType = {"issues": "read", "organization_projects": "write"}
_LINK_PERMISSIONS: AppPermissionsType = {"issues": "read", "organization_projects": "write", "contents": "read"}
_EMPTY = ""
_MALFORMED_RESPONSE = "malformed response"
_REFUSAL_WITH_TYPES = "{}: {}"
_TYPE_SEPARATOR = ","

_READ_OWNER = """query($owner:String!, $name:String!) {
  repository(owner:$owner, name:$name) { id owner { id __typename } }
}"""
_LIST_PROJECTS = """query($id:ID!, $cursor:String) {
  node(id:$id) { ... on Organization {
    projectsV2(first:100, after:$cursor) {
      nodes { id number title creator { __typename login } }
      pageInfo { hasNextPage endCursor }
    }
  } }
}"""
_READ_PROJECT = """query($login:String!, $number:Int!) {
  organization(login:$login) { projectV2(number:$number) { id number title } }
}"""
_FIND_ITEM = """query($id:ID!) {
  node(id:$id) { ... on Issue { projectItems(first:50, includeArchived:true) { nodes { id project { id } } } } }
}"""
_CREATE_PROJECT = """mutation($ownerId:ID!, $title:String!) {
  createProjectV2(input:{ownerId:$ownerId, title:$title}) { projectV2 { id number title } }
}"""
_READ_BOARD = """query($id:ID!) {
  node(id:$id) { ... on ProjectV2 {
    id number title readme closed
    fields(first:50) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } } }
    views(first:50) { nodes { id name layout filter } }
    workflows(first:50) { nodes { id } }
    repositories(first:100) { nodes { id } }
  } }
}"""
_UPDATE_README = """mutation($projectId:ID!, $readme:String!) {
  updateProjectV2(input:{projectId:$projectId, readme:$readme, closed:false}) { projectV2 { id } }
}"""
_UPDATE_SELECT_OPTIONS = """mutation($fieldId:ID!, $options:[ProjectV2SingleSelectFieldOptionInput!]) {
  updateProjectV2Field(input:{fieldId:$fieldId, singleSelectOptions:$options}) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
  }
}"""
_CREATE_SELECT_FIELD = """mutation($projectId:ID!, $name:String!, $options:[ProjectV2SingleSelectFieldOptionInput!]) {
  createProjectV2Field(input:{projectId:$projectId, dataType:SINGLE_SELECT, name:$name, singleSelectOptions:$options}) {
    projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
  }
}"""
_CREATE_VIEW = """mutation($projectId:ID!, $name:String!, $layout:ProjectV2ViewLayout!) {
  createProjectV2View(input:{projectId:$projectId, name:$name, layout:$layout}) { projectV2View { id } }
}"""
_UPDATE_VIEW_FILTER = """mutation($viewId:ID!, $filter:String!) {
  updateProjectV2View(input:{viewId:$viewId, filter:$filter}) { projectV2View { id } }
}"""
_DELETE_WORKFLOW = """mutation($workflowId:ID!) {
  deleteProjectV2Workflow(input:{workflowId:$workflowId}) { deletedWorkflowId }
}"""
_LINK_PROJECT = """mutation($projectId:ID!, $repositoryId:ID!) {
  linkProjectV2ToRepository(input:{projectId:$projectId, repositoryId:$repositoryId}) { repository { id } }
}"""
_ADD_ITEM = """mutation($projectId:ID!, $contentId:ID!) {
  addProjectV2ItemById(input:{projectId:$projectId, contentId:$contentId}) { item { id } }
}"""
_SET_ITEM_OPTION = """mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!, $optionId:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$projectId, itemId:$itemId, fieldId:$fieldId, value:{singleSelectOptionId:$optionId}
  }) { projectV2Item { id } }
}"""
_CLEAR_ITEM_FIELD = """mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!) {
  clearProjectV2ItemFieldValue(input:{projectId:$projectId, itemId:$itemId, fieldId:$fieldId}) {
    projectV2Item { id }
  }
}"""
_DELETE_ITEM = """mutation($projectId:ID!, $itemId:ID!) {
  deleteProjectV2Item(input:{projectId:$projectId, itemId:$itemId}) { deletedItemId }
}"""


class GitHubBoardOperation(StrEnum):
    """Closed set of provider operations made for the board, named in refusals."""

    READ_OWNER = "read_owner"
    LIST_PROJECTS = "list_projects"
    READ_PROJECT = "read_project"
    FIND_ITEM = "find_item"
    CREATE_PROJECT = "create_project"
    READ_BOARD = "read_board"
    UPDATE_README = "update_readme"
    UPDATE_SELECT_OPTIONS = "update_select_options"
    CREATE_SELECT_FIELD = "create_select_field"
    CREATE_VIEW = "create_view"
    UPDATE_VIEW_FILTER = "update_view_filter"
    DELETE_WORKFLOW = "delete_workflow"
    LINK_PROJECT = "link_project"
    ADD_ITEM = "add_item"
    SET_ITEM_OPTION = "set_item_option"
    CLEAR_ITEM_FIELD = "clear_item_field"
    DELETE_ITEM = "delete_item"


class GitHubBoardLayout(StrEnum):
    """Saved view layouts a board is set up with."""

    BOARD = "BOARD_LAYOUT"
    TABLE = "TABLE_LAYOUT"


class GitHubBoardColor(StrEnum):
    """Option colors GitHub accepts for a single-select option."""

    GRAY = "GRAY"
    BLUE = "BLUE"
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"
    PINK = "PINK"
    PURPLE = "PURPLE"


class _GraphQLErrorType(StrEnum):
    """The error types of a GraphQL failure that are safe to name in a refusal; everything else is dropped."""

    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    INSUFFICIENT_SCOPES = "INSUFFICIENT_SCOPES"
    RATE_LIMITED = "RATE_LIMITED"
    UNPROCESSABLE = "UNPROCESSABLE"


class _Key(StrEnum):
    """GraphQL variable names and response keys used by the board requests."""

    OWNER = "owner"
    NAME = "name"
    ID = "id"
    CURSOR = "cursor"
    ORGANIZATION = "organization"
    PROJECT_BY_NUMBER = "projectV2"
    PROJECT_ITEMS = "projectItems"
    NODE = "node"
    NODES = "nodes"
    REPOSITORY = "repository"
    TYPENAME = "__typename"
    PROJECTS_V2 = "projectsV2"
    PAGE_INFO = "pageInfo"
    HAS_NEXT_PAGE = "hasNextPage"
    END_CURSOR = "endCursor"
    CREATOR = "creator"
    LOGIN = "login"
    NUMBER = "number"
    TITLE = "title"
    OWNER_ID = "ownerId"
    CREATE_PROJECT = "createProjectV2"
    PROJECT = "projectV2"
    README = "readme"
    CLOSED = "closed"
    FIELDS = "fields"
    OPTIONS = "options"
    VIEWS = "views"
    LAYOUT = "layout"
    FILTER = "filter"
    WORKFLOWS = "workflows"
    REPOSITORIES = "repositories"
    PROJECT_ID = "projectId"
    FIELD_ID = "fieldId"
    VIEW_ID = "viewId"
    WORKFLOW_ID = "workflowId"
    REPOSITORY_ID = "repositoryId"
    CONTENT_ID = "contentId"
    ITEM_ID = "itemId"
    OPTION_ID = "optionId"
    DESCRIPTION = "description"
    COLOR = "color"
    CREATE_FIELD = "createProjectV2Field"
    UPDATE_FIELD = "updateProjectV2Field"
    PROJECT_FIELD = "projectV2Field"
    CREATE_VIEW = "createProjectV2View"
    PROJECT_VIEW = "projectV2View"
    ADD_ITEM = "addProjectV2ItemById"
    ITEM = "item"


@dataclass(frozen=True)
class GitHubBoardOption:
    """One single-select option to write; `option_id` keeps an existing option so items keep their value."""

    name: str
    color: GitHubBoardColor
    description: str
    option_id: str | None = None


def _graphql_refusal(operation: GitHubBoardOperation, failed: GraphQLFailed) -> GitHubIORefused:
    error_types: set[_GraphQLErrorType] = set()
    for error in failed.response.errors or ():
        try:
            error_types.add(_GraphQLErrorType(error.type))
        except ValueError:
            continue
    detail = (
        _REFUSAL_WITH_TYPES.format(operation.value, _TYPE_SEPARATOR.join(sorted(error_types)))
        if error_types
        else operation.value
    )
    if _GraphQLErrorType.NOT_FOUND in error_types:
        return GitHubIORefused(GitHubIOFailure.NOT_FOUND, detail=detail)
    if _GraphQLErrorType.RATE_LIMITED in error_types:
        return GitHubIORefused(GitHubIOFailure.RATE_LIMITED, detail=detail)
    if error_types:
        return GitHubIORefused(GitHubIOFailure.VALIDATION_REFUSED, detail=detail)
    return GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=detail)


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) else _EMPTY


def _number(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)


def _nodes(connection: object) -> tuple[Mapping[str, object], ...]:
    nodes = _mapping(connection).get(_Key.NODES)
    if not isinstance(nodes, list):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)
    return tuple(_mapping(node) for node in nodes)


def _project(node: Mapping[str, object]) -> GitHubBoardProject:
    return GitHubBoardProject(
        project_id=_text(node.get(_Key.ID)), number=_number(node.get(_Key.NUMBER)), title=_text(node.get(_Key.TITLE))
    )


def _select_field(node: Mapping[str, object]) -> GitHubBoardSelectField:
    options = node.get(_Key.OPTIONS)
    if not isinstance(options, list):
        raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)
    return GitHubBoardSelectField(
        field_id=_text(node.get(_Key.ID)),
        name=_text(node.get(_Key.NAME)),
        options=tuple(
            (_text(_mapping(option).get(_Key.ID)), _text(_mapping(option).get(_Key.NAME))) for option in options
        ),
    )


def _option_input(option: GitHubBoardOption) -> dict[str, str]:
    payload = {
        _Key.NAME.value: option.name,
        _Key.COLOR.value: option.color.value,
        _Key.DESCRIPTION.value: option.description,
    }
    if option.option_id is not None:
        payload[_Key.ID.value] = option.option_id
    return payload


class GitHubBoardIO:
    """Make the board's GitHub Projects requests for one repository as the project's platform App."""

    def __init__(self, repository: GitHubRepositoryIdentity, assignment: GitHubActorAssignment) -> None:
        self.repository = repository
        self.assignment = assignment
        self._transport = GitHubTransport(GitHubRepositoryScope(repository.repository_id, repository.repository))

    def submit[Result](self, work: Callable[[GitHubBoardIO], Awaitable[Result]]) -> Future[Result]:
        """Queue one serialized unit of board work on the shared GitHub I/O loop."""
        return submit_serialized_unit(partial(work, self))

    async def read_owner(self) -> GitHubBoardOwner:
        """Read the repository's node ID and whether an organization owns it."""
        owner, name = split_repository(self.repository.repository)
        data = await self._graphql(GitHubBoardOperation.READ_OWNER, _READ_OWNER, {_Key.OWNER: owner, _Key.NAME: name})
        repository = _mapping(data.get(_Key.REPOSITORY))
        account = _mapping(repository.get(_Key.OWNER))
        return GitHubBoardOwner(
            repository_id=_text(repository.get(_Key.ID)),
            owner_id=_text(account.get(_Key.ID)),
            is_organization=account.get(_Key.TYPENAME) == GitHubAccountKind.ORGANIZATION,
        )

    async def find_project(self, owner_id: str, title: str) -> GitHubBoardProject | None:
        """Find the project the platform App created with `title`, so an interrupted setup never makes a second."""
        cursor: str | None = None
        while True:
            data = await self._graphql(
                GitHubBoardOperation.LIST_PROJECTS, _LIST_PROJECTS, {_Key.ID: owner_id, _Key.CURSOR: cursor}
            )
            connection = _mapping(_mapping(data.get(_Key.NODE)).get(_Key.PROJECTS_V2))
            for node in _nodes(connection):
                creator = _mapping(node.get(_Key.CREATOR))
                if node.get(_Key.TITLE) == title and self._created_by_app(creator):
                    return _project(node)
            page = _mapping(connection.get(_Key.PAGE_INFO))
            if not page.get(_Key.HAS_NEXT_PAGE):
                return None
            next_cursor = page.get(_Key.END_CURSOR)
            if not isinstance(next_cursor, str) or next_cursor == cursor:
                raise GitHubIORefused(GitHubIOFailure.UNAVAILABLE, detail=_MALFORMED_RESPONSE)
            cursor = next_cursor

    async def find_project_by_number(self, login: str, number: int) -> GitHubBoardProject | None:
        """Read the organization's project with this number; None when GitHub has no such project."""
        try:
            data = await self._graphql(
                GitHubBoardOperation.READ_PROJECT, _READ_PROJECT, {_Key.LOGIN: login, _Key.NUMBER: number}
            )
        except GitHubIORefused as refused:
            if refused.reason is GitHubIOFailure.NOT_FOUND:
                return None
            raise
        project = _mapping(data.get(_Key.ORGANIZATION)).get(_Key.PROJECT_BY_NUMBER)
        return _project(_mapping(project)) if project is not None else None

    async def create_project(self, owner_id: str, title: str) -> GitHubBoardProject:
        """Create the organization project; the title is set in this request so a rerun can find it."""
        data = await self._graphql(
            GitHubBoardOperation.CREATE_PROJECT, _CREATE_PROJECT, {_Key.OWNER_ID: owner_id, _Key.TITLE: title}
        )
        return _project(_mapping(_mapping(data.get(_Key.CREATE_PROJECT)).get(_Key.PROJECT)))

    async def read_board(self, project_id: str) -> GitHubBoardState:
        """Read the project as setup compares it: README, single-select fields, views, workflows and links."""
        data = await self._graphql(GitHubBoardOperation.READ_BOARD, _READ_BOARD, {_Key.ID: project_id})
        node = _mapping(data.get(_Key.NODE))
        if not node:
            raise GitHubIORefused(GitHubIOFailure.NOT_FOUND, detail=GitHubBoardOperation.READ_BOARD.value)
        return GitHubBoardState(
            project=_project(node),
            readme=_optional_text(node.get(_Key.README)),
            closed=node.get(_Key.CLOSED) is True,
            fields=tuple(_select_field(field) for field in _nodes(node.get(_Key.FIELDS)) if field),
            views=tuple(
                GitHubBoardView(
                    view_id=_text(view.get(_Key.ID)),
                    name=_text(view.get(_Key.NAME)),
                    layout=_text(view.get(_Key.LAYOUT)),
                    filter=_optional_text(view.get(_Key.FILTER)),
                )
                for view in _nodes(node.get(_Key.VIEWS))
            ),
            workflow_ids=tuple(_text(workflow.get(_Key.ID)) for workflow in _nodes(node.get(_Key.WORKFLOWS))),
            linked_repository_ids=frozenset(
                _text(repository.get(_Key.ID)) for repository in _nodes(node.get(_Key.REPOSITORIES))
            ),
        )

    async def set_readme(self, project_id: str, readme: str) -> None:
        """Write the board's README and reopen the project if someone closed it."""
        await self._graphql(
            GitHubBoardOperation.UPDATE_README, _UPDATE_README, {_Key.PROJECT_ID: project_id, _Key.README: readme}
        )

    async def set_select_options(self, field_id: str, options: Sequence[GitHubBoardOption]) -> GitHubBoardSelectField:
        """Replace a single-select field's options; options given their ID keep the items set to them."""
        data = await self._graphql(
            GitHubBoardOperation.UPDATE_SELECT_OPTIONS,
            _UPDATE_SELECT_OPTIONS,
            {_Key.FIELD_ID: field_id, _Key.OPTIONS: [_option_input(option) for option in options]},
        )
        return _select_field(_mapping(_mapping(data.get(_Key.UPDATE_FIELD)).get(_Key.PROJECT_FIELD)))

    async def create_select_field(
        self, project_id: str, name: str, options: Sequence[GitHubBoardOption]
    ) -> GitHubBoardSelectField:
        """Create a single-select field with its options."""
        data = await self._graphql(
            GitHubBoardOperation.CREATE_SELECT_FIELD,
            _CREATE_SELECT_FIELD,
            {
                _Key.PROJECT_ID: project_id,
                _Key.NAME: name,
                _Key.OPTIONS: [_option_input(option) for option in options],
            },
        )
        return _select_field(_mapping(_mapping(data.get(_Key.CREATE_FIELD)).get(_Key.PROJECT_FIELD)))

    async def create_view(self, project_id: str, name: str, layout: GitHubBoardLayout) -> str:
        """Create a saved view and return its ID."""
        data = await self._graphql(
            GitHubBoardOperation.CREATE_VIEW,
            _CREATE_VIEW,
            {_Key.PROJECT_ID: project_id, _Key.NAME: name, _Key.LAYOUT: layout.value},
        )
        return _text(_mapping(_mapping(data.get(_Key.CREATE_VIEW)).get(_Key.PROJECT_VIEW)).get(_Key.ID))

    async def set_view_filter(self, view_id: str, view_filter: str) -> None:
        """Set a saved view's filter."""
        await self._graphql(
            GitHubBoardOperation.UPDATE_VIEW_FILTER,
            _UPDATE_VIEW_FILTER,
            {_Key.VIEW_ID: view_id, _Key.FILTER: view_filter},
        )

    async def delete_workflow(self, workflow_id: str) -> None:
        """Delete one of the project's built-in workflows; deletion is the only way to switch one off."""
        await self._graphql(GitHubBoardOperation.DELETE_WORKFLOW, _DELETE_WORKFLOW, {_Key.WORKFLOW_ID: workflow_id})

    async def link_project(self, project_id: str, repository_id: str) -> None:
        """Link the project to the repository; GitHub asks the App for the repository's Contents read permission."""
        await self._graphql(
            GitHubBoardOperation.LINK_PROJECT,
            _LINK_PROJECT,
            {_Key.PROJECT_ID: project_id, _Key.REPOSITORY_ID: repository_id},
            permissions=_LINK_PERMISSIONS,
        )

    async def find_item(self, project_id: str, issue_node_id: str) -> str | None:
        """Find the board item an issue already has on the project, however this computer came to lack its ID."""
        data = await self._graphql(GitHubBoardOperation.FIND_ITEM, _FIND_ITEM, {_Key.ID: issue_node_id})
        items = _nodes(_mapping(data.get(_Key.NODE)).get(_Key.PROJECT_ITEMS))
        return next(
            (_text(item.get(_Key.ID)) for item in items if _mapping(item.get(_Key.PROJECT)).get(_Key.ID) == project_id),
            None,
        )

    async def add_item(self, project_id: str, issue_node_id: str) -> str:
        """Add an issue to the project and return its board item ID; adding an issue already there returns its item."""
        data = await self._graphql(
            GitHubBoardOperation.ADD_ITEM,
            _ADD_ITEM,
            {_Key.PROJECT_ID: project_id, _Key.CONTENT_ID: issue_node_id},
        )
        return _text(_mapping(_mapping(data.get(_Key.ADD_ITEM)).get(_Key.ITEM)).get(_Key.ID))

    async def set_item_option(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        """Set a single-select field of a board item."""
        await self._graphql(
            GitHubBoardOperation.SET_ITEM_OPTION,
            _SET_ITEM_OPTION,
            {
                _Key.PROJECT_ID: project_id,
                _Key.ITEM_ID: item_id,
                _Key.FIELD_ID: field_id,
                _Key.OPTION_ID: option_id,
            },
        )

    async def clear_item_field(self, project_id: str, item_id: str, field_id: str) -> None:
        """Clear a field of a board item."""
        await self._graphql(
            GitHubBoardOperation.CLEAR_ITEM_FIELD,
            _CLEAR_ITEM_FIELD,
            {_Key.PROJECT_ID: project_id, _Key.ITEM_ID: item_id, _Key.FIELD_ID: field_id},
        )

    async def delete_item(self, project_id: str, item_id: str) -> None:
        """Remove an item from the board; the issue itself is untouched."""
        await self._graphql(
            GitHubBoardOperation.DELETE_ITEM, _DELETE_ITEM, {_Key.PROJECT_ID: project_id, _Key.ITEM_ID: item_id}
        )

    def _created_by_app(self, creator: Mapping[str, object]) -> bool:
        login = creator.get(_Key.LOGIN)
        if not isinstance(login, str):
            return False
        presented = github_app_bot_login(login) if creator.get(_Key.TYPENAME) == GitHubAccountKind.BOT else login
        return presented == self.assignment.actor.login

    async def _graphql(
        self,
        operation: GitHubBoardOperation,
        document: str,
        variables: Mapping[_Key, object],
        *,
        permissions: AppPermissionsType = _BOARD_PERMISSIONS,
    ) -> Mapping[str, object]:
        arguments = {key.value: value for key, value in variables.items()}

        async def request(client: Any) -> Mapping[str, object]:
            try:
                return cast(Mapping[str, object], await client.graphql.arequest(document, arguments))
            except GraphQLFailed as failed:
                raise _graphql_refusal(operation, failed) from None

        return await self._transport.call(self.assignment, permissions, operation, request)
