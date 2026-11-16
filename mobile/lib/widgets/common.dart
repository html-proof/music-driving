import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../core/errors/app_exception.dart';
import '../core/theme/app_theme.dart';

String formatDuration(Duration d) {
  final h = d.inHours;
  final m = d.inMinutes.remainder(60);
  final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
  return h > 0 ? '$h:${m.toString().padLeft(2, '0')}:$s' : '$m:$s';
}

/// Cached artwork with a placeholder; downsamples to the displayed size to save memory.
class ArtworkImage extends StatelessWidget {
  const ArtworkImage({super.key, required this.url, this.size = 48, this.radius = 4, this.circle = false, this.icon = Icons.music_note});

  final String? url;
  final double size;
  final double radius;
  final bool circle;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final placeholder = Container(
      width: size,
      height: size,
      color: AppColors.surfaceHigh,
      child: Icon(icon, color: AppColors.textSecondary, size: size * 0.4),
    );
    final dpr = MediaQuery.devicePixelRatioOf(context);
    final image = url == null || url!.isEmpty
        ? placeholder
        : kIsWeb
            // The provider's image CDN sends no CORS headers, which the web renderer
            // needs to decode images itself; fall back to a plain <img> element there.
            ? Image.network(
                url!,
                width: size,
                height: size,
                fit: BoxFit.cover,
                webHtmlElementStrategy: WebHtmlElementStrategy.fallback,
                errorBuilder: (_, _, _) => placeholder,
              )
            : CachedNetworkImage(
            imageUrl: url!,
            width: size,
            height: size,
            fit: BoxFit.cover,
            memCacheWidth: (size * dpr).round(),
            placeholder: (_, _) => placeholder,
            errorWidget: (_, _, _) => placeholder,
          );
    return circle
        ? ClipOval(child: image)
        : ClipRRect(borderRadius: BorderRadius.circular(radius), child: image);
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.subtitle, this.action});

  final String title;
  final String? subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 24, 8, 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                if (subtitle != null)
                  Text(subtitle!, style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
              ],
            ),
          ),
          ?action,
        ],
      ),
    );
  }
}

class ErrorView extends StatelessWidget {
  const ErrorView({super.key, required this.error, this.onRetry});

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final e = AppException.from(error);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(e.isNetwork ? Icons.wifi_off : Icons.error_outline, size: 48, color: AppColors.textSecondary),
            const SizedBox(height: 12),
            Text(e.message, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textSecondary)),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
            ],
          ],
        ),
      ),
    );
  }
}

class EmptyView extends StatelessWidget {
  const EmptyView({super.key, required this.icon, required this.message});
  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 48, color: AppColors.textSecondary),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textSecondary)),
          ]),
        ),
      );
}

const loadingView = Center(child: CircularProgressIndicator());

void showError(BuildContext context, Object error) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(AppException.from(error).message)));
}

void showMessage(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}
