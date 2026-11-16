import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/home/home_screen.dart';
import 'package:melodia/models/catalog.dart';

void main() {
  test('home feed reads the languages that could not be loaded', () {
    final feed = HomeFeed.fromJson({
      'greeting': 'Good evening',
      'sections': <dynamic>[],
      'errors': {'trending_tamil': 'Music provider is currently unavailable'},
      'unavailable_languages': ['Tamil'],
    });
    expect(feed.unavailableLanguages, ['Tamil']);
    // Older backends don't send the field.
    expect(HomeFeed.fromJson({'greeting': 'Hi', 'sections': <dynamic>[]}).unavailableLanguages, isEmpty);
  });

  test('notice names every missing language', () {
    expect(UnavailableLanguagesNotice.message(['Tamil']), startsWith('Tamil songs couldn'));
    expect(UnavailableLanguagesNotice.message(['Hindi', 'Tamil', 'Punjabi']), startsWith('Hindi, Tamil and Punjabi songs'));
  });

  testWidgets('notice is shown on screen', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: UnavailableLanguagesNotice(languages: ['Tamil', 'Telugu'])),
    ));
    expect(find.textContaining('Tamil and Telugu songs couldn'), findsOneWidget);
  });
}
