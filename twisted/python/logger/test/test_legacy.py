# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Test cases for L{twisted.python.logger._legacy}.
"""

from time import time
import logging as py_logging

from zope.interface.verify import verifyObject, BrokenMethodImplementation

from twisted.trial import unittest

from twisted.python import context
from twisted.python import log as legacyLog
from twisted.python.failure import Failure

from .._levels import LogLevel
from .._observer import ILogObserver
from .._format import formatEvent
from .._legacy import LegacyLogObserverWrapper
from .._legacy import publishToNewObserver



class LegacyLogObserverWrapperTests(unittest.TestCase):
    """
    Tests for L{LegacyLogObserverWrapper}.
    """

    def test_interface(self):
        """
        L{LegacyLogObserverWrapper} is an L{ILogObserver}.
        """
        legacyObserver = lambda e: None
        observer = LegacyLogObserverWrapper(legacyObserver)
        try:
            verifyObject(ILogObserver, observer)
        except BrokenMethodImplementation as e:
            self.fail(e)


    def test_repr(self):
        """
        L{LegacyLogObserverWrapper} returns the expected string.
        """
        class LegacyObserver(object):
            def __repr__(self):
                return "<Legacy Observer>"

            def __call__(self):
                return

        observer = LegacyLogObserverWrapper(LegacyObserver())

        self.assertEqual(
            repr(observer),
            "LegacyLogObserverWrapper(<Legacy Observer>)"
        )


    def observe(self, event):
        """
        Send an event to a wrapped legacy observer and capture the event as
        seen by that observer.

        @param event: an event
        @type event: L{dict}

        @return: the event as observed by the legacy wrapper
        """
        events = []

        legacyObserver = lambda e: events.append(e)
        observer = LegacyLogObserverWrapper(legacyObserver)
        observer(event)
        self.assertEqual(len(events), 1)

        return events[0]


    def forwardAndVerify(self, event):
        """
        Send an event to a wrapped legacy observer and verify that its data is
        preserved.

        @param event: an event
        @type event: L{dict}

        @return: the event as observed by the legacy wrapper
        """
        # Make sure keys that are expected by the logging system are present
        event.setdefault("log_time", time())
        event.setdefault("log_system", "-")

        # Send a copy: don't mutate me, bro
        observed = self.observe(dict(event))

        # Don't expect modifications
        for key, value in event.items():
            self.assertIn(key, observed)
            self.assertEqual(observed[key], value)

        return observed


    def test_forward(self):
        """
        Basic forwarding: event keys as observed by a legacy observer are the
        same.
        """
        self.forwardAndVerify(dict(foo=1, bar=2))


    def test_time(self):
        """
        The new-style C{"log_time"} key is copied to the old-style C{"time"}
        key.
        """
        stamp = time()
        event = self.forwardAndVerify(dict(log_time=stamp))
        self.assertEqual(event["time"], stamp)


    def test_timeAlreadySet(self):
        """
        The new-style C{"log_time"} key does not step on a pre-existing
        old-style C{"time"} key.
        """
        stamp = time()
        event = self.forwardAndVerify(dict(log_time=stamp + 1, time=stamp))
        self.assertEqual(event["time"], stamp)


    def test_system(self):
        """
        The new-style C{"log_system"} key is copied to the old-style
        C{"system"} key.
        """
        event = self.forwardAndVerify(dict(log_system="foo"))
        self.assertEqual(event["system"], "foo")


    def test_systemAlreadySet(self):
        """
        The new-style C{"log_system"} key does not step on a pre-existing
        old-style C{"system"} key.
        """
        event = self.forwardAndVerify(dict(log_system="foo", system="bar"))
        self.assertEqual(event["system"], "bar")


    def test_noSystem(self):
        """
        If the new-style C{"log_system"} key is absent, the old-style
        C{"system"} key is set to C{"-"}.
        """
        # Don't use forwardAndVerify(), since that's sets log_system.
        event = dict(log_time=time())
        observed = self.observe(dict(event))
        self.assertEqual(observed["system"], "-")


    def test_pythonLogLevelNotSet(self):
        """
        The new-style C{"log_level"} key is not translated to the old-style
        C{"logLevel"} key.

        Events are forwarded from the old module from to new module and are
        then seen by old-style observers.
        We don't want to add unexpected keys to old-style events.
        """
        event = self.forwardAndVerify(dict(log_level=LogLevel.info))
        self.assertNotIn("logLevel", event)


    def test_stringPythonLogLevel(self):
        """
        If a stdlib log level was provided as a string (eg. C{"WARNING"}) in
        the legacy "logLevel" key, it does not get converted to a number.
        The documentation suggested that numerical values should be used but
        this was not a requirement.
        """
        event = self.forwardAndVerify(dict(
            logLevel="WARNING",  # py_logging.WARNING is 30
        ))
        self.assertEqual(event["logLevel"], "WARNING")


    def test_message(self):
        """
        The old-style C{"message"} key is added, even if no new-style
        C{"log_format"} is given, as it is required, but may be empty.
        """
        event = self.forwardAndVerify(dict())
        self.assertEqual(event["message"], ())  # "message" is a tuple


    def test_messageAlreadySet(self):
        """
        The old-style C{"message"} key is not modified if it already exists.
        """
        event = self.forwardAndVerify(dict(message=("foo", "bar")))
        self.assertEqual(event["message"], ("foo", "bar"))


    def test_format(self):
        """
        Formatting is translated such that text is rendered correctly, even
        though old-style logging doesn't use PEP 3101 formatting.
        """
        event = self.forwardAndVerify(
            dict(log_format="Hello, {who}!", who="world")
        )
        self.assertEqual(
            legacyLog.textFromEventDict(event),
            "Hello, world!"
        )


    def test_formatAlreadySet(self):
        """
        Formatting is not altered if the old-style C{"format"} key already
        exists.
        """
        event = self.forwardAndVerify(
            dict(log_format="Hello!", format="Howdy!")
        )
        self.assertEqual(legacyLog.textFromEventDict(event), "Howdy!")


    def eventWithFailure(self, **values):
        """
        Create an new-style event with a captured failure.

        @param values: Additional values to include in the event.
        @type values: L{dict}

        @return: the new event
        @rtype: L{dict}
        """
        failure = Failure(RuntimeError("nyargh!"))
        return self.forwardAndVerify(dict(
            log_failure=failure,
            log_format="oopsie...",
            **values
        ))


    def test_failure(self):
        """
        Captured failures in the new style set the old-style C{"failure"},
        C{"isError"}, and C{"why"} keys.
        """
        event = self.eventWithFailure()
        self.assertIs(event["failure"], event["log_failure"])
        self.assertTrue(event["isError"])
        self.assertEqual(event["why"], "oopsie...")


    def test_failureAlreadySet(self):
        """
        Captured failures in the new style do not step on a pre-existing
        old-style C{"failure"} key.
        """
        failure = Failure(RuntimeError("Weak salsa!"))
        event = self.eventWithFailure(failure=failure)
        self.assertIs(event["failure"], failure)


    def test_isErrorAlreadySet(self):
        """
        Captured failures in the new style do not step on a pre-existing
        old-style C{"isError"} key.
        """
        event = self.eventWithFailure(isError=0)
        self.assertEqual(event["isError"], 0)


    def test_whyAlreadySet(self):
        """
        Captured failures in the new style do not step on a pre-existing
        old-style C{"failure"} key.
        """
        event = self.eventWithFailure(why="blah")
        self.assertEqual(event["why"], "blah")



class PublishToNewObserverTests(unittest.TestCase):
    """
    Tests for L{publishToNewObserver}.
    """

    def setUp(self):
        self.events = []
        self.observer = self.events.append


    def legacyEvent(self, *message, **values):
        """
        Return a basic old-style event as would be created by L{legacyLog.msg}.

        @param message: a message event value in the legacy event format
        @type message: L{tuple} of L{bytes}

        @param values: additional event values in the legacy event format
        @type event: L{dict}

        @return: a legacy event
        """
        event = (context.get(legacyLog.ILogContext) or {}).copy()
        event.update(values)
        event["message"] = message
        event["time"] = time()
        return event


    def test_observed(self):
        """
        The observer is called exactly once.
        """
        publishToNewObserver(
            self.observer, self.legacyEvent(), legacyLog.textFromEventDict
        )
        self.assertEqual(len(self.events), 1)


    def test_time(self):
        """
        The old-style C{"time"} key is copied to the new-style C{"log_time"}
        key.
        """
        publishToNewObserver(
            self.observer, self.legacyEvent(), legacyLog.textFromEventDict
        )
        self.assertEqual(
            self.events[0]["log_time"], self.events[0]["time"]
        )


    def test_message(self):
        """
        An published old-style event should format as text in the same way as
        the given C{textFromEventDict} callable would format it.
        """
        def textFromEventDict(event):
            return "".join(reversed(" ".join(event["message"])))

        event = self.legacyEvent("Hello,", "world!")
        text = textFromEventDict(event)

        publishToNewObserver(self.observer, event, textFromEventDict)
        self.assertEqual(formatEvent(self.events[0]), text)


    def test_defaultLogLevel(self):
        """
        Published event should have log level of L{LogLevel.info}.
        """
        publishToNewObserver(
            self.observer, self.legacyEvent(), legacyLog.textFromEventDict
        )
        self.assertEqual(self.events[0]["log_level"], LogLevel.info)


    def test_isError(self):
        """
        If C{"isError"} is set to C{1} (true) on the legacy event, the
        C{"log_level"} key should get set to L{LogLevel.critical}.
        """
        publishToNewObserver(
            self.observer,
            self.legacyEvent(isError=1),
            legacyLog.textFromEventDict
        )
        self.assertEqual(self.events[0]["log_level"], LogLevel.critical)


    def test_stdlibLogLevel(self):
        """
        If the old-style C{"logLevel"} key is set to a standard library logging
        level, using a predefined (L{int}) constant, the new-style
        C{"log_level"} key should get set to the corresponding log level.
        """
        publishToNewObserver(
            self.observer,
            self.legacyEvent(logLevel=py_logging.WARNING),
            legacyLog.textFromEventDict
        )
        self.assertEqual(self.events[0]["log_level"], LogLevel.warn)


    def test_stdlibLogLevelWithString(self):
        """
        If the old-style C{"logLevel"} key is set to a standard library logging
        level, using a string value, the new-style C{"log_level"} key should
        get set to the corresponding log level.
        """
        publishToNewObserver(
            self.observer,
            self.legacyEvent(logLevel="WARNING"),
            legacyLog.textFromEventDict
        )
        self.assertEqual(self.events[0]["log_level"], LogLevel.warn)


    def test_stdlibLogLevelWithGarbage(self):
        """
        If the old-style C{"logLevel"} key is set to a standard library logging
        level, using an unknown value, the new-style C{"log_level"} key should
        not get set.
        """
        publishToNewObserver(
            self.observer,
            self.legacyEvent(logLevel="Foo!!!!!"),
            legacyLog.textFromEventDict
        )
        self.assertNotIn("log_level", self.events[0])


    def test_defaultNamespace(self):
        """
        Published event should have a namespace of C{"log_legacy"} to indicate
        that it was forwarded from legacy logging.
        """
        publishToNewObserver(
            self.observer, self.legacyEvent(), legacyLog.textFromEventDict
        )
        self.assertEqual(self.events[0]["log_namespace"], "log_legacy")


    def test_system(self):
        """
        The old-style C{"system"} key is copied to the new-style
        C{"log_system"} key.
        """
        publishToNewObserver(
            self.observer, self.legacyEvent(), legacyLog.textFromEventDict
        )
        self.assertEqual(
            self.events[0]["log_system"], self.events[0]["system"]
        )
