import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import '../../widgets/common.dart';
import '../home/home_screen.dart';
import '../session/session_controller.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  Future<void> _run(BuildContext context, Future<void> Function() action) async {
    try {
      await action();
    } catch (e) {
      if (context.mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    final user = session.user;
    final ctrl = ref.read(sessionProvider.notifier);
    if (user == null) return const Scaffold(body: loadingView);
    final prefs = user.preferences;

    return Scaffold(
      appBar: AppBar(title: const Text('Profile & settings')),
      body: ListView(children: [
        ListTile(
          leading: CircleAvatar(
            radius: 28,
            backgroundColor: AppColors.accent,
            child: Text(user.displayName.characters.first.toUpperCase(),
                style: const TextStyle(fontSize: 24, color: Colors.black, fontWeight: FontWeight.bold)),
          ),
          title: Text(user.displayName, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          subtitle: const Text('Your library is saved for this device'),
          trailing: IconButton(
            tooltip: 'Edit name',
            icon: const Icon(Icons.edit_outlined),
            onPressed: () async {
              final controller = TextEditingController(text: user.displayName);
              final name = await showDialog<String>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('Display name'),
                  content: TextField(controller: controller, autofocus: true, maxLength: 100),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
                    TextButton(onPressed: () => Navigator.pop(ctx, controller.text.trim()), child: const Text('Save')),
                  ],
                ),
              );
              if (name != null && name.isNotEmpty && context.mounted) await _run(context, () => ctrl.updateName(name));
            },
          ),
        ),
        if (session.offline)
          const ListTile(leading: Icon(Icons.wifi_off), title: Text('Offline — changes need a connection')),
        const Divider(),
        const _Header('Playback'),
        ListTile(
          leading: const Icon(Icons.graphic_eq),
          title: const Text('Streaming quality'),
          subtitle: Text(AppConfig.audioQualities[prefs.audioQuality] ?? prefs.audioQuality),
          onTap: () async {
            final q = await showDialog<String>(
              context: context,
              builder: (ctx) => SimpleDialog(
                title: const Text('Streaming quality'),
                children: [
                  for (final e in AppConfig.audioQualities.entries)
                    SimpleDialogOption(
                      onPressed: () => Navigator.pop(ctx, e.key),
                      child: Row(children: [
                        Icon(e.key == prefs.audioQuality ? Icons.radio_button_checked : Icons.radio_button_unchecked, size: 20),
                        const SizedBox(width: 12),
                        Text(e.value),
                      ]),
                    ),
                  const Padding(
                    padding: EdgeInsets.fromLTRB(24, 8, 24, 0),
                    child: Text('If a song isn\'t available at this quality, the closest verified quality is used.',
                        style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                  ),
                ],
              ),
            );
            if (q != null && context.mounted) await _run(context, () => ctrl.updatePreferences(audioQuality: q));
          },
        ),
        SwitchListTile(
          secondary: const Icon(Icons.explicit_outlined),
          title: const Text('Allow explicit content'),
          value: prefs.allowExplicit,
          onChanged: (v) => _run(context, () => ctrl.updatePreferences(allowExplicit: v)),
        ),
        const _Header('Music languages'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 4, children: [
            for (final lang in AppConfig.supportedLanguages)
              FilterChip(
                label: Text(lang),
                selected: prefs.languages.contains(lang),
                onSelected: (sel) {
                  final next = [...prefs.languages];
                  sel ? next.add(lang) : next.remove(lang);
                  if (next.isEmpty) {
                    showMessage(context, 'Pick at least one language');
                    return;
                  }
                  _run(context, () async {
                    await ctrl.updatePreferences(languages: next);
                    ref.invalidate(homeFeedProvider);
                  });
                },
              ),
          ]),
        ),
        const SizedBox(height: 16),
        const Divider(),
        const _Header('Data'),
        ListTile(
          leading: const Icon(Icons.delete_forever, color: Colors.redAccent),
          title: const Text('Delete my data', style: TextStyle(color: Colors.redAccent)),
          subtitle: const Text('Erases your playlists, liked songs and listening history'),
          onTap: () async {
            final ok = await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('Delete all your data?'),
                content: const Text(
                    'Your playlists, liked songs, followed artists and history will be permanently deleted. '
                    'This cannot be undone.'),
                actions: [
                  TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                  TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete')),
                ],
              ),
            );
            if (ok == true && context.mounted) {
              await _run(context, ctrl.deleteMyData);
              if (context.mounted) showMessage(context, 'Your data was deleted');
            }
          },
        ),
        const SizedBox(height: 24),
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text(
            'No sign-in needed: your library is tied to this device. Uninstalling the app '
            'or clearing its data starts a new, empty library.\n\n'
            'Music catalogue and streams are provided by Gaana via the unofficial GaanaPy API. '
            'Lyrics from LRCLIB.',
            style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
          ),
        ),
      ]),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        child: Text(text, style: const TextStyle(fontWeight: FontWeight.bold, color: AppColors.accent)),
      );
}
