# encoding: utf-8

"""
Copyright (c) 2012 Marian Steinbach

Hiermit wird unentgeltlich jeder Person, die eine Kopie der Software und
der zugehörigen Dokumentationen (die "Software") erhält, die Erlaubnis
erteilt, sie uneingeschränkt zu benutzen, inklusive und ohne Ausnahme, dem
Recht, sie zu verwenden, kopieren, ändern, fusionieren, verlegen
verbreiten, unterlizenzieren und/oder zu verkaufen, und Personen, die diese
Software erhalten, diese Rechte zu geben, unter den folgenden Bedingungen:

Der obige Urheberrechtsvermerk und dieser Erlaubnisvermerk sind in allen
Kopien oder Teilkopien der Software beizulegen.

Die Software wird ohne jede ausdrückliche oder implizierte Garantie
bereitgestellt, einschließlich der Garantie zur Benutzung für den
vorgesehenen oder einen bestimmten Zweck sowie jeglicher Rechtsverletzung,
jedoch nicht darauf beschränkt. In keinem Fall sind die Autoren oder
Copyrightinhaber für jeglichen Schaden oder sonstige Ansprüche haftbar zu
machen, ob infolge der Erfüllung eines Vertrages, eines Delikts oder anders
im Zusammenhang mit der Software oder sonstiger Verwendung der Software
entstanden.
"""

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from datetime import datetime


class Queue(object):
    """Abstrakte Warteschlange, die zum Abarbeiten von Sitzungen,
    Dokumenten etc. benutzt wird. Bereits verarbeitete Elemente
    werden weiterhin gespeichert und können nicht erneut hinzugefügt
    werden."""

    def __init__(self, name, config, db):
        self.name = name
        self.config = config
        self.db = db.db
        self.db.queue.ensure_index([('rs', 1), ('qname', 1), ('key', 1)], unique=True)

    def has_next(self):
        """Gibt True zurück, wenn Elemente in der Warteschlange sind."""
        if len(self) > 0:
            return True
        return False

    def add(self, key_or_element):
        """Fügt ein Element zur Warteschlange hinzu. Wenn das Element schon
        in der Warteschlange ist, wird es nicht noch mal hinzugefügt, jedoch
        kein Fehler erzeugt. Sollte das Element schon mal hinzugefügt und
        bereits verarbeitet worden sein, wird ebenfalls kein Fehler erzeugt.

        Das Element muss ein dict mit den Eigenschaften 'key' (Pflicht) und
        optional 'payload' sein."""
        key = None
        payload = None
        if type(key_or_element) == dict:
            key = key_or_element['key']
            if 'payload' in key_or_element:
                payload = key_or_element['payload']
        else:
            key = key_or_element
        job = {
            'rs': self.config.RS,
            'qname': self.name,
            'status': 'OPEN',
            'key': key,
            'failures': 0,
            'last_modified': datetime.utcnow()
        }
        if payload is not None:
            job['payload'] = payload
        try:
            self.db.queue.save(job)
        except DuplicateKeyError:
            pass

    def get(self):
        """Gibt ein Element aus der Warteschlange zurück und markiert es
        als "IN_PROGRESS". Wenn kein Element mehr vorhanden ist, wird
        ein KeyError geworfen."""
        # BTW: we don't care for the sort order right now.
        query = {
            'rs': self.config.RS,
            'qname': self.name,
            'status': 'OPEN'
        }
        update = {
            '$set': {
                'status': 'IN_PROGRESS',
                'last_modified': datetime.utcnow()
            }
        }
        find = self.db.queue.find_and_modify(query=query,
            update=update)
        out = {'key': find['key']}
        if 'payload' in find:
            out['payload'] = find['payload']
        return out

    def __len__(self):
        """
        Returns the number of OPEN jobs
        """
        query = {
            'rs': self.config.RS,
            'qname': self.name,
            'status': 'OPEN'
        }
        num = self.db.queue.find(query).count()
        return num

    def resolve_job(self, key_or_element):
        """
        Mark a job as "DONE". The job can be either indicated
        by a dict with a "key" element or a key int/string directly
        """
        key = None
        if type(key_or_element) == dict:
            key = key_or_element['key']
        else:
            key = key_or_element
        query = {
            'rs': self.config.RS,
            'qname': self.name,
            'key': key
        }
        update = {
            '$set': {
                'status': 'DONE',
                'last_modified': datetime.utcnow()
            }
        }
        self.db.queue.find_and_modify(query=query,
            update=update)

    def mark_failed(self, key_or_element):
        """
        Add 1 to the failure count of a job.
        If the failure count reaches 3, set the job status
        to "FAILED".
        """
        key = None
        if type(key_or_element) == dict:
            key = key_or_element['key']
        else:
            key = key_or_element
        query = {
            'rs': self.config.RS,
            'qname': self.name,
            'key': key
        }
        job = self.db.queue.find_one(query)
        update = {
            '$inc': {
                'failures': 1
            }
        }
        if job['failures'] >= 2:
            update['$set'] = {
                'status': 'FAILED'
            }
        self.db.queue.update(
            {'_id': job['_id']},
            update)

    def garbage_collect(self):
        """
        Remove all DONE elements from queue
        """
        query = {
            'rs': self.config.RS,
            'qname': self.name,
            'status': 'DONE'
        }
        self.db.queue.remove(query)


if __name__ == '__main__':
    """Tests"""
    connection = MongoClient()
    db = connection.test
    class cfg(object):
        RS = "foobar"
    config = cfg
    q = Queue('TEST_QUEUE', config, db)
    assert q.has_next() == False
    q.add({'key': 1})
    assert q.has_next() == True
    q.add({'key': 1})
    q.add({'key': 2})
    q.add({'key': 3})
    assert len(q) == 3
    job1 = q.get()
    assert len(q) == 2
    job2 = q.get()
    assert len(q) == 1
    job3 = q.get()
    assert len(q) == 0
    assert q.has_next() == False
    q.resolve_job(job1)
    q.resolve_job(job2)
    q.mark_failed(job3)
    q.mark_failed(job3)
    q.mark_failed(job3)
    q.garbage_collect()
