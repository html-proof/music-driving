import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

/// SQLite-backed JSON cache for offline access to metadata the user has already
/// loaded (home feed, liked songs, playlists, followed artists, profile).
/// Stream URLs are never stored here.
abstract class LocalCache {
  Future<Map<String, dynamic>?> read(String key);
  Future<void> write(String key, Object json);
  Future<void> clear();
}

class SqliteLocalCache implements LocalCache {
  Database? _db;

  Future<Database> _open() async {
    return _db ??= await openDatabase(
      p.join(await getDatabasesPath(), 'melodia_cache.db'),
      version: 1,
      onCreate: (db, _) => db.execute(
        'CREATE TABLE cache (key TEXT PRIMARY KEY, json TEXT NOT NULL, updated_at INTEGER NOT NULL)',
      ),
    );
  }

  @override
  Future<Map<String, dynamic>?> read(String key) async {
    final db = await _open();
    final rows = await db.query('cache', where: 'key = ?', whereArgs: [key], limit: 1);
    if (rows.isEmpty) return null;
    return {'data': jsonDecode(rows.first['json'] as String), 'updated_at': rows.first['updated_at']};
  }

  @override
  Future<void> write(String key, Object json) async {
    final db = await _open();
    await db.insert(
      'cache',
      {'key': key, 'json': jsonEncode(json), 'updated_at': DateTime.now().millisecondsSinceEpoch},
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  @override
  Future<void> clear() async {
    final db = await _open();
    await db.delete('cache');
  }
}

/// In-memory implementation used by tests.
class MemoryLocalCache implements LocalCache {
  final _data = <String, Object>{};

  @override
  Future<Map<String, dynamic>?> read(String key) async =>
      _data.containsKey(key) ? {'data': jsonDecode(jsonEncode(_data[key])), 'updated_at': 0} : null;

  @override
  Future<void> write(String key, Object json) async => _data[key] = json;

  @override
  Future<void> clear() async => _data.clear();
}
