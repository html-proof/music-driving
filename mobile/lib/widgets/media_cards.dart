import 'package:flutter/material.dart';

import '../core/theme/app_theme.dart';
import 'common.dart';

/// Square card used in horizontal carousels (albums, playlists, tracks, artists).
class MediaCard extends StatelessWidget {
  const MediaCard({
    super.key,
    required this.imageUrl,
    required this.title,
    this.subtitle,
    required this.onTap,
    this.circle = false,
    this.size = 140,
  });

  final String? imageUrl;
  final String title;
  final String? subtitle;
  final VoidCallback onTap;
  final bool circle;
  final double size;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: SizedBox(
        width: size,
        child: Column(
          crossAxisAlignment: circle ? CrossAxisAlignment.center : CrossAxisAlignment.start,
          children: [
            ArtworkImage(url: imageUrl, size: size, radius: 6, circle: circle, icon: circle ? Icons.person : Icons.album),
            const SizedBox(height: 8),
            Text(title, maxLines: 2, overflow: TextOverflow.ellipsis, textAlign: circle ? TextAlign.center : TextAlign.start,
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            if (subtitle != null)
              Text(subtitle!, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}

class HorizontalList extends StatelessWidget {
  const HorizontalList({super.key, required this.itemCount, required this.itemBuilder, this.height = 210});

  final int itemCount;
  final IndexedWidgetBuilder itemBuilder;
  final double height;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        scrollDirection: Axis.horizontal,
        itemCount: itemCount,
        separatorBuilder: (_, _) => const SizedBox(width: 14),
        itemBuilder: itemBuilder,
      ),
    );
  }
}
