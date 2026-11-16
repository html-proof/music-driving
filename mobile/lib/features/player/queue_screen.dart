import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_theme.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import 'player_providers.dart';

class QueueScreen extends ConsumerWidget {
  const QueueScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final items = ref.watch(queueProvider).value ?? const [];
    final index = ref.watch(playbackStateProvider).value?.queueIndex ?? 0;
    final handler = ref.read(audioHandlerProvider);

    if (items.isEmpty) {
      return Scaffold(appBar: AppBar(title: const Text('Queue')),
          body: const EmptyView(icon: Icons.queue_music, message: 'Your queue is empty'));
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Queue')),
      body: ReorderableListView.builder(
        buildDefaultDragHandles: false,
        itemCount: items.length,
        onReorderItem: (from, to) => handler.moveInQueue(from, to),
        itemBuilder: (context, i) {
          final item = items[i];
          final isCurrent = i == index;
          return Dismissible(
            key: ValueKey('${item.id}-$i'),
            direction: DismissDirection.endToStart,
            background: Container(
              color: Colors.red.shade900,
              alignment: Alignment.centerRight,
              padding: const EdgeInsets.only(right: 24),
              child: const Icon(Icons.delete),
            ),
            onDismissed: (_) => handler.removeFromQueue(i),
            child: ListTile(
              leading: ArtworkImage(url: item.artUri?.toString(), size: 44),
              title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: isCurrent ? AppColors.accent : (i < index ? AppColors.textSecondary : null))),
              subtitle: Text(item.artist ?? '', maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textSecondary)),
              onTap: () => handler.skipToQueueItem(i),
              trailing: ReorderableDragStartListener(index: i, child: const Icon(Icons.drag_handle)),
            ),
          );
        },
      ),
    );
  }
}
