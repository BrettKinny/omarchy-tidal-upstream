"""The favourites endpoint, through HTTP: how a list is paged."""

import importlib
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

# Import the HTTP module without starting Mopidy's extension entry point.
package_name = "_tidal_library_test"
package = ModuleType(package_name)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "backend" / "mopidy_omarchy_tidal")]
sys.modules[package_name] = package
http = importlib.import_module(f"{package_name}.http")


class TestLibrary(AsyncHTTPTestCase):
    def get_app(self):
        self.favorites = SimpleNamespace(
            tracks=Mock(return_value=[]), albums=Mock(return_value=[]),
            playlists=Mock(return_value=[]))
        session = SimpleNamespace(user=SimpleNamespace(favorites=self.favorites))
        provider = SimpleNamespace(get=lambda: session)
        # Whatever the handler takes besides the provider and the config --
        # `core` today -- is not something /library uses.
        wanted = inspect.signature(http.BaseHandler.initialize).parameters
        kwargs = {name: None for name in wanted if name != "self"}
        kwargs.update(provider=provider, config={})
        return Application([(r"/library", http.LibraryHandler, kwargs)])

    def test_a_short_page_is_not_the_end_when_tidal_says_there_are_more(self):
        """A favourite that is no longer available keeps its position and is
        left out of the page, so pages come back short in the middle."""
        self.favorites.tracks.return_value = [object()] * 97
        self.favorites.get_tracks_count = Mock(return_value=195)
        body = json.loads(self.fetch("/library?section=tracks&limit=100&offset=0").body)
        assert (body["more"], body["total"]) == (True, 195)
        body = json.loads(self.fetch("/library?section=tracks&limit=100&offset=100").body)
        assert body["more"] is False

    def test_without_a_total_a_short_page_still_ends_the_list(self):
        self.favorites.albums.return_value = [object()] * 3
        body = json.loads(self.fetch("/library?section=albums&limit=100").body)
        assert body["more"] is False
        assert "total" not in body
        self.favorites.get_albums_count = Mock(side_effect=RuntimeError("tidal said no"))
        assert json.loads(self.fetch("/library?section=albums&limit=3").body)["more"] is True

    def test_playlists_are_asked_for_fifty_at_most(self):
        """Tidal answers 400 for more, and one failed page drops every
        favourites list to browse refs for the rest of the session."""
        body = json.loads(self.fetch("/library?section=playlists&limit=100&offset=50").body)
        self.favorites.playlists.assert_called_once_with(limit=50, offset=50)
        assert body["limit"] == 50, "said back, so the next page starts in the right place"
